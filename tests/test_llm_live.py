"""Live provider smoke: one gpt-5.5 call with a forced tool call (and the follow-up turn that re-sends
its reasoning items), one Sonnet call, one embedding. Calls the real APIs (well under $0.05), so it is
skipped unless LIVE_LLM=1:

    LIVE_LLM=1 .venv/bin/python -m pytest tests/test_llm_live.py -q -s

Prints each call's model, stop reason, tokens and cost; never a key."""

import os

import pytest

from pharmassist.agent.tools import tool_defs
from pharmassist.config import PROJECT_ROOT, load_config
from pharmassist.llm.base import Message, TextPart, ToolResult
from pharmassist.llm.router import router_from_config

pytestmark = pytest.mark.skipif(os.environ.get("LIVE_LLM") != "1", reason="calls the LLM APIs; set LIVE_LLM=1")

ASK = ("This is a connectivity test. Call submit_answer exactly once with status 'answered', assumption null, "
       "answer 'ok', citations [{\"doc_id\": \"test_doc\", \"page\": 1}] and conflicts_noted []. Then stop.")
SYSTEM = "You are a test harness for a pharmacy assistant. Follow the instruction literally."


@pytest.fixture(scope="module")
def router():
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if not os.environ.get(key):
            pytest.skip(f"{key} is not set")
    return router_from_config(load_config())


def _report(label, c):
    u = c.usage
    print(f"\n{label}: provider={c.provider} model={c.model} stop={c.stop_reason} tokens(in/out/cache_read/cache_write)="
          f"{u.input}/{u.output}/{u.cache_read}/{u.cache_write} cost=${c.cost_usd:.5f} duration={c.duration_s}s")


def test_gpt55_forced_tool_call_and_a_follow_up_turn(router):
    tools = tool_defs(False)
    primary = router.primary
    messages = [Message("user", [TextPart(ASK)])]
    c = primary.provider.complete(model=primary.model, system=SYSTEM, messages=messages, tools=tools, max_tokens=2000,
                                  effort="low", timeout_s=60, tool_choice="submit_answer")
    _report("gpt-5.5 forced submit_answer", c)
    assert c.provider == "openai" and c.model.startswith("gpt-5.5") and c.stop_reason == "tool_use"
    call = c.message.tool_calls[0]
    assert call.name == "submit_answer" and set(call.arguments) == {"status", "assumption", "answer", "citations", "conflicts_noted"}
    assert call.arguments["citations"] == [{"doc_id": "test_doc", "page": 1}]   # strict schema honoured
    items = c.message.provider_state["openai"]["items"]
    assert any(i["type"] == "function_call" for i in items)
    assert c.cost_usd > 0 and c.usage.input > 0
    # the follow-up turn re-sends the reasoning/function_call items with the tool result
    messages += [c.message, Message("tool", [ToolResult(call.id, "recorded")]),
                 Message("user", [TextPart("Reply with the single word DONE and no tool call.")])]
    c2 = primary.provider.complete(model=primary.model, system=SYSTEM, messages=messages, tools=tools, max_tokens=500,
                                   effort="low", timeout_s=60)
    _report("gpt-5.5 follow-up", c2)
    assert c2.stop_reason == "end_turn" and "DONE" in c2.message.text.upper()


def test_sonnet_call(router):
    fb = router.fallback
    # no tools: with submit_answer offered, Sonnet rightly follows its "call exactly once" description
    c = fb.provider.complete(model=fb.model, system=SYSTEM,
                             messages=[Message("user", [TextPart("Reply with the single word OK and nothing else.")])],
                             tools=[], max_tokens=300, effort="low", timeout_s=60)
    _report("sonnet", c)
    assert c.provider == "anthropic" and c.model.startswith("claude-sonnet") and c.stop_reason == "end_turn"
    assert "OK" in c.message.text.upper() and c.cost_usd > 0
    assert c.message.provider_state["anthropic"]["refusal_fallback"] is False


def test_router_fallback_path_live(router):
    """A forced fallback: the primary gets an impossible model name (a 400, non-retryable) and Sonnet answers."""
    from pharmassist.llm.router import Role
    broken = Role(router.primary.provider, "gpt-5.5-does-not-exist", prices=router.primary.prices)
    r = type(router)(broken, router.fallback, attempts=1, backoff_s=0, embed_client=router._embed_client)
    c = r.complete(system=SYSTEM, messages=[Message("user", [TextPart("Reply with the single word OK.")])],
                   tools=[], timeout_s=60)
    _report("router fallback", c)
    assert c.fallback_used is True and c.provider == "anthropic"


def test_embedding_is_3072_dims(router):
    v = router.embed(["Ozempic pen: preferred or PA?"])
    assert len(v) == 1 and len(v[0]) == 3072
    print(f"\nembedding: 1 text, {len(v[0])} dims")
