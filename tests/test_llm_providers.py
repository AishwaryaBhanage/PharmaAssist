"""Provider translation: canonical messages <-> OpenAI Responses items and Anthropic Messages blocks,
checked against the installed SDKs' own types (responses are built with the SDK models, so the
recorded shapes are the real ones). No network: the SDK clients are stand-ins that capture kwargs."""

import json
from types import SimpleNamespace as NS

import httpx
import pytest

from pharmassist.llm import anthropic_provider as A
from pharmassist.llm import openai_provider as O
from pharmassist.llm import pricing
from pharmassist.llm.base import Message, ProviderError, TextPart, ToolCall, ToolResult, ToolSpec, Usage

PRICES = {"input": 5.0, "output": 30.0, "cache_read": 0.5, "cache_write": 0}
SEARCH = ToolSpec("search_documents", "Search.", {"type": "object", "properties": {"query": {"type": "string"}},
                                                "required": ["query"]})
SUBMIT = ToolSpec("submit_answer", "Submit.", {"type": "object", "properties": {"answer": {"type": "string"}},
                                             "required": ["answer"], "additionalProperties": False}, strict=True)
THREAD = [
    Message("user", [TextPart("Today's date: 2026-10-18\n\nQuestion: Ozempic?")]),
    Message("assistant", [TextPart("Let me look."), ToolCall("call_1", "search_documents", {"query": "Ozempic"})]),
    Message("tool", [ToolResult("call_1", "[{\"doc_id\": \"ny_medicaid_pdl\"}]"),]),
    Message("user", [TextPart("Lookup budget spent.")]),
]


# ---- OpenAI ----

def openai_response(*output, status="completed", incomplete=None, usage=None, model="gpt-5.5"):
    from openai.types.responses import Response
    usage = usage or {"input_tokens": 1200, "input_tokens_details": {"cached_tokens": 500, "cache_write_tokens": 0},
                      "output_tokens": 100, "output_tokens_details": {"reasoning_tokens": 40}, "total_tokens": 1300}
    body = {"id": "resp_1", "created_at": 0, "model": model, "object": "response", "output": list(output),
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": [], "status": status, "usage": usage}
    if incomplete:
        body["incomplete_details"] = {"reason": incomplete}
    return Response.model_validate(body)


REASONING = {"id": "rs_1", "type": "reasoning", "summary": [], "encrypted_content": "enc-abc"}
CALL = {"type": "function_call", "id": "fc_1", "call_id": "call_9", "name": "search_documents",
        "arguments": "{\"query\": \"Ozempic PA\"}", "status": "completed"}
MSG = {"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
       "content": [{"type": "output_text", "text": "Searching.", "annotations": []}]}


class OpenAIClient:
    def __init__(self, *responses):
        self._queue, self.calls = list(responses), []
        self.responses = NS(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_openai_input_items_from_a_canonical_thread():
    items = O.to_input(THREAD)
    assert items == [
        {"role": "user", "content": "Today's date: 2026-10-18\n\nQuestion: Ozempic?"},
        {"role": "assistant", "content": "Let me look."},
        {"type": "function_call", "call_id": "call_1", "name": "search_documents", "arguments": "{\"query\": \"Ozempic\"}"},
        {"type": "function_call_output", "call_id": "call_1", "output": "[{\"doc_id\": \"ny_medicaid_pdl\"}]"},
        {"role": "user", "content": "Lookup budget spent."},
    ]


def test_openai_request_shape_strict_tools_effort_and_stateless_reasoning():
    client = OpenAIClient(openai_response(REASONING, CALL))
    p = O.OpenAIProvider(client, prices=PRICES)
    c = p.complete(model="gpt-5.5", system="SYS", messages=THREAD[:1], tools=[SEARCH, SUBMIT], max_tokens=4096,
                   effort="medium", timeout_s=12.5)
    kw = client.calls[0]
    assert kw["model"] == "gpt-5.5" and kw["instructions"] == "SYS" and kw["timeout"] == 12.5
    assert kw["reasoning"] == {"effort": "medium"} and kw["max_output_tokens"] == 4096
    assert kw["store"] is False and kw["include"] == ["reasoning.encrypted_content"] and kw["tool_choice"] == "auto"
    assert kw["tools"] == [
        {"type": "function", "name": "search_documents", "description": "Search.", "parameters": SEARCH.input_schema,
         "strict": False},
        {"type": "function", "name": "submit_answer", "description": "Submit.", "parameters": SUBMIT.input_schema,
         "strict": True}]
    assert c.provider == "openai" and c.model == "gpt-5.5" and c.stop_reason == "tool_use" and c.raw_id == "resp_1"
    assert c.message.tool_calls == [ToolCall("call_9", "search_documents", {"query": "Ozempic PA"})]
    # the uncached remainder is `input`; cached tokens are priced at the cached-input rate
    assert c.usage == Usage(input=700, output=100, cache_read=500, cache_write=0)
    assert c.cost_usd == pytest.approx((700 * 5 + 100 * 30 + 500 * 0.5) / 1e6) == pricing.cost_usd(c.usage, PRICES)


def test_openai_reasoning_items_are_carried_and_resent_verbatim():
    client = OpenAIClient(openai_response(REASONING, MSG, CALL))
    c = O.OpenAIProvider(client).complete(model="gpt-5.5", system="S", messages=THREAD[:1], tools=[SEARCH],
                                          max_tokens=100, effort="low", timeout_s=5)
    items = c.message.provider_state["openai"]["items"]
    assert [i["type"] for i in items] == ["reasoning", "message", "function_call"]
    assert items[0]["encrypted_content"] == "enc-abc" and c.message.text == "Searching."
    # next turn: the assistant message is re-sent as its own items, followed by the tool result
    thread = THREAD[:1] + [c.message, Message("tool", [ToolResult("call_9", "[]", is_error=True)])]
    assert O.to_input(thread) == [
        {"role": "user", "content": THREAD[0].text}, *items,
        {"type": "function_call_output", "call_id": "call_9", "output": "[tool error] []"}]


def test_openai_round_trip_through_a_foreign_assistant_turn():
    """An assistant turn served by Anthropic (no openai items) is rebuilt from the canonical parts."""
    foreign = Message("assistant", [ToolCall("toolu_01A", "read_page", {"doc_id": "d", "page": 3})],
                      provider_state={"anthropic": {"content": [{"type": "tool_use", "id": "toolu_01A", "name": "read_page",
                                                                 "input": {"doc_id": "d", "page": 3}}]}})
    items = O.to_input(THREAD[:1] + [foreign, Message("tool", [ToolResult("toolu_01A", "page text")])])
    assert items[1] == {"type": "function_call", "call_id": "toolu_01A", "name": "read_page",
                        "arguments": "{\"doc_id\": \"d\", \"page\": 3}"}
    assert items[2]["call_id"] == "toolu_01A"


@pytest.mark.parametrize("output, status, incomplete, expected", [
    ((MSG,), "completed", None, "end_turn"),
    ((REASONING, CALL), "completed", None, "tool_use"),
    ((MSG,), "incomplete", "max_output_tokens", "max_tokens"),
    (({**MSG, "content": [{"type": "refusal", "refusal": "no"}]},), "completed", None, "refusal"),
])
def test_openai_stop_reasons(output, status, incomplete, expected):
    _, stop = O.from_response(openai_response(*output, status=status, incomplete=incomplete), "gpt-5.5")
    assert stop == expected


def test_openai_malformed_tool_json_is_a_malformed_provider_error():
    bad = {**CALL, "arguments": "{\"query\": "}
    with pytest.raises(ProviderError) as e:
        O.from_response(openai_response(bad), "gpt-5.5")
    assert e.value.malformed and not e.value.retryable and "Ozempic" not in str(e.value)
    with pytest.raises(ProviderError, match="not an object") as e:
        O.from_response(openai_response({**CALL, "arguments": "[1, 2]"}), "gpt-5.5")
    assert e.value.malformed


def _http(status):
    req = httpx.Request("POST", "https://api.example/v1")
    return httpx.Response(status, request=req, json={"error": {"message": "x"}})


@pytest.mark.parametrize("make, retryable, status", [
    (lambda: __import__("openai").RateLimitError("rate", response=_http(429), body=None), True, 429),
    (lambda: __import__("openai").InternalServerError("down", response=_http(503), body=None), True, 503),
    (lambda: __import__("openai").ConflictError("c", response=_http(409), body=None), True, 409),
    (lambda: __import__("openai").APITimeoutError(httpx.Request("POST", "https://api.example")), True, None),
    (lambda: __import__("openai").APIConnectionError(request=httpx.Request("POST", "https://api.example")), True, None),
    (lambda: __import__("openai").BadRequestError("bad", response=_http(400), body=None), False, 400),
    (lambda: __import__("openai").AuthenticationError("auth", response=_http(401), body=None), False, 401),
])
def test_openai_errors_are_classified(make, retryable, status):
    client = OpenAIClient(make())
    with pytest.raises(ProviderError) as e:
        O.OpenAIProvider(client).complete(model="m", system="s", messages=THREAD[:1], tools=[], max_tokens=1,
                                          effort="low", timeout_s=1)
    assert e.value.retryable is retryable and e.value.status == status and e.value.provider == "openai"


def test_openai_tool_choice_forces_a_named_tool():
    client = OpenAIClient(openai_response(CALL), openai_response(CALL))
    p = O.OpenAIProvider(client)
    p.complete(model="m", system="s", messages=THREAD[:1], tools=[SEARCH], max_tokens=1, effort="low", timeout_s=1,
               tool_choice="search_documents")
    p.complete(model="m", system="s", messages=THREAD[:1], tools=[SEARCH], max_tokens=1, effort="low", timeout_s=1,
               tool_choice="required")
    assert client.calls[0]["tool_choice"] == {"type": "function", "name": "search_documents"}
    assert client.calls[1]["tool_choice"] == "required"


# ---- Anthropic ----

def anthropic_response(*content, stop="end_turn", model="claude-sonnet-5-5", iterations=None):
    from anthropic.types.beta import BetaMessage
    body = {"id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": list(content),
            "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 500,
                      "cache_creation_input_tokens": 20}}
    m = BetaMessage.model_validate(body)
    if iterations is not None:
        m.usage.iterations = iterations
    return m


TEXT = {"type": "text", "text": "Checking."}
THINK = {"type": "thinking", "thinking": "hmm", "signature": "sig-1"}
USE = {"type": "tool_use", "id": "toolu_7", "name": "search_documents", "input": {"query": "Ozempic PA"}}


class AnthropicClient:
    def __init__(self, *responses):
        self.queue, self.calls = list(responses), []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_anthropic_turns_from_a_canonical_thread_merge_consecutive_user_turns():
    assert A.to_messages(THREAD) == [
        {"role": "user", "content": [{"type": "text", "text": "Today's date: 2026-10-18\n\nQuestion: Ozempic?"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Let me look."},
                                          {"type": "tool_use", "id": "call_1", "name": "search_documents",
                                           "input": {"query": "Ozempic"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1",
                                      "content": "[{\"doc_id\": \"ny_medicaid_pdl\"}]", "is_error": False},
                                     {"type": "text", "text": "Lookup budget spent."}]},
    ]


def test_anthropic_request_shape_effort_caching_strict_and_refusal_fallback():
    client = AnthropicClient(anthropic_response(THINK, TEXT, USE, stop="tool_use"))
    p = A.AnthropicProvider(client, prices={"input": 2, "output": 10, "cache_read": 0.2, "cache_write": 2.5},
                            refusal_fallback=True)
    c = p.complete(model="claude-sonnet-5-5", system="SYS", messages=THREAD[:1], tools=[SEARCH, SUBMIT],
                   max_tokens=4096, effort="high", timeout_s=7)
    kw = client.calls[0]
    assert kw["model"] == "claude-sonnet-5-5" and kw["system"] == "SYS" and kw["max_tokens"] == 4096
    assert kw["output_config"] == {"effort": "high"} and kw["cache_control"] == {"type": "ephemeral"}
    assert kw["timeout"] == 7 and "tool_choice" not in kw
    assert kw["betas"] == [A.FALLBACK_BETA] and kw["fallbacks"] == "default"
    assert kw["tools"] == [{"name": "search_documents", "description": "Search.", "input_schema": SEARCH.input_schema},
                           {"name": "submit_answer", "description": "Submit.", "input_schema": SUBMIT.input_schema,
                            "strict": True}]
    assert c.stop_reason == "tool_use" and c.message.text == "Checking." and c.provider == "anthropic"
    assert c.message.tool_calls == [ToolCall("toolu_7", "search_documents", {"query": "Ozempic PA"})]
    assert c.usage == Usage(1000, 100, 500, 20) and c.cost_usd == pytest.approx((2000 + 1000 + 100 + 50) / 1e6)
    assert c.message.provider_state["anthropic"]["refusal_fallback"] is False


def test_anthropic_without_the_beta_sends_no_fallback_keys():
    client = AnthropicClient(anthropic_response(TEXT))
    A.AnthropicProvider(client).complete(model="m", system="s", messages=THREAD[:1], tools=[], max_tokens=1,
                                         effort="low", timeout_s=1)
    assert "betas" not in client.calls[0] and "fallbacks" not in client.calls[0]


def test_anthropic_thinking_blocks_are_carried_and_resent_verbatim():
    client = AnthropicClient(anthropic_response(THINK, USE, stop="tool_use"))
    c = A.AnthropicProvider(client).complete(model="m", system="s", messages=THREAD[:1], tools=[SEARCH],
                                             max_tokens=1, effort="low", timeout_s=1)
    content = c.message.provider_state["anthropic"]["content"]
    assert content == [{"type": "thinking", "thinking": "hmm", "signature": "sig-1"}, USE]
    thread = THREAD[:1] + [c.message, Message("tool", [ToolResult("toolu_7", "rows", is_error=False)])]
    turns = A.to_messages(thread)
    assert turns[1] == {"role": "assistant", "content": content}
    assert turns[2]["content"] == [{"type": "tool_result", "tool_use_id": "toolu_7", "content": "rows", "is_error": False}]


def test_anthropic_rebuilds_a_turn_served_by_openai_from_the_canonical_parts():
    """Fallback mid-thread: OpenAI's reasoning items are dropped, its call ids kept (both accept [A-Za-z0-9_-])."""
    openai_turn = Message("assistant", [ToolCall("call_abc123", "search_documents", {"query": "x"})],
                          provider_state={"openai": {"items": [REASONING, CALL]}})
    turns = A.to_messages(THREAD[:1] + [openai_turn, Message("tool", [ToolResult("call_abc123", "[]")])])
    assert turns[1]["content"] == [{"type": "tool_use", "id": "call_abc123", "name": "search_documents",
                                    "input": {"query": "x"}}]
    assert turns[2]["content"][0]["tool_use_id"] == "call_abc123"


def test_anthropic_refusal_and_fallback_hop_are_visible():
    resp = anthropic_response(stop="refusal")
    _, stop = A.from_response(resp)
    assert stop == "refusal"
    served = anthropic_response(TEXT, model="claude-sonnet-5", iterations=[NS(type="message"), NS(type="fallback_message")])
    client = AnthropicClient(served)
    c = A.AnthropicProvider(client, refusal_fallback=True).complete(model="claude-sonnet-5-5", system="s",
                                                                    messages=THREAD[:1], tools=[], max_tokens=1,
                                                                    effort="low", timeout_s=1)
    assert c.model == "claude-sonnet-5" and c.requested_model == "claude-sonnet-5-5"
    assert c.message.provider_state["anthropic"]["refusal_fallback"] is True and c.fallback_used is False


@pytest.mark.parametrize("make, retryable, status", [
    (lambda: __import__("anthropic").RateLimitError("rate", response=_http(429), body=None), True, 429),
    (lambda: __import__("anthropic").InternalServerError("down", response=_http(500), body=None), True, 500),
    (lambda: __import__("anthropic").OverloadedError("busy", response=_http(529), body=None), True, 529),
    (lambda: __import__("anthropic").APITimeoutError(httpx.Request("POST", "https://api.example")), True, None),
    (lambda: __import__("anthropic").BadRequestError("bad", response=_http(400), body=None), False, 400),
    (lambda: __import__("anthropic").AuthenticationError("auth", response=_http(401), body=None), False, 401),
])
def test_anthropic_errors_are_classified(make, retryable, status):
    client = AnthropicClient(make())
    with pytest.raises(ProviderError) as e:
        A.AnthropicProvider(client).complete(model="m", system="s", messages=THREAD[:1], tools=[], max_tokens=1,
                                             effort="low", timeout_s=1)
    assert e.value.retryable is retryable and e.value.status == status and e.value.provider == "anthropic"


def test_anthropic_tool_choice_mapping():
    client = AnthropicClient(anthropic_response(USE, stop="tool_use"), anthropic_response(USE, stop="tool_use"))
    p = A.AnthropicProvider(client)
    for choice in ("required", "submit_answer"):
        p.complete(model="m", system="s", messages=THREAD[:1], tools=[SEARCH], max_tokens=1, effort="low",
                   timeout_s=1, tool_choice=choice)
    assert client.calls[0]["tool_choice"] == {"type": "any"}
    assert client.calls[1]["tool_choice"] == {"type": "tool", "name": "submit_answer"}


def test_errors_never_carry_message_content():
    """Neither provider's ProviderError mentions what was sent; the SDK message is reduced to its class and status."""
    import anthropic
    import openai
    for prov, client, exc in [
        (O.OpenAIProvider, OpenAIClient, openai.BadRequestError("Invalid 'input[0].content': Ozempic", response=_http(400), body=None)),
        (A.AnthropicProvider, AnthropicClient, anthropic.BadRequestError("messages.0: Ozempic", response=_http(400), body=None)),
    ]:
        with pytest.raises(ProviderError) as e:
            prov(client(exc)).complete(model="m", system="s", messages=THREAD[:1], tools=[], max_tokens=1,
                                       effort="low", timeout_s=1)
        assert "Ozempic" not in str(e.value) and "400" in str(e.value)


def test_pricing_handles_missing_keys_and_dicts():
    assert pricing.cost_usd(Usage(1_000_000, 0, 0, 0), {"input": 5.0}) == 5.0
    assert pricing.cost_usd({"input": 0, "output": 1_000_000}, {"output": 30}) == 30.0
    assert pricing.cost_usd(Usage(), None) == 0.0
