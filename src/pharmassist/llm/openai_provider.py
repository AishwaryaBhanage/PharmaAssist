"""OpenAI on the Responses API, translated to and from the canonical format in `llm.base`.

Stateless use (`store=False` with `reasoning.encrypted_content` requested): nothing about a question
is kept on OpenAI's side, and the assistant's own output items (reasoning, message, function_call)
are carried in `Message.provider_state["openai"]` and re-sent verbatim on the next turn, so a
multi-turn tool thread continues without losing the reasoning context. An assistant message that
came from another provider (the router fell back mid-thread, or vice versa) is rebuilt from its
canonical parts instead, which the API accepts.

Nothing here logs message content; errors carry the SDK's status and class name only.
"""

from __future__ import annotations

import json
import re
import time
from typing import Literal, Sequence

from pharmassist.llm import pricing
from pharmassist.llm.base import (Completion, Effort, Message, ProviderError, TextPart, ToolCall, ToolResult,
                                  ToolSpec, Usage)

RETRYABLE_STATUS = {408, 409, 429}
ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def safe_id(call_id: str) -> str:
    """Tool call ids travel between providers; both accept [A-Za-z0-9_-], so anything else is dropped."""
    return ID_CHARS.sub("", call_id or "") or "call_0"


def tool_param(t: ToolSpec) -> dict:
    return {"type": "function", "name": t.name, "description": t.description,
            "parameters": t.input_schema, "strict": bool(t.strict)}


def to_input(messages: Sequence[Message]) -> list[dict]:
    """Canonical messages -> Responses `input` items."""
    items: list[dict] = []
    for m in messages:
        if m.role == "user":
            items.append({"role": "user", "content": m.text})
        elif m.role == "assistant":
            own = (m.provider_state or {}).get("openai")
            if own and own.get("items"):
                items.extend(own["items"])      # reasoning + message + function_call items, as returned
                continue
            if m.text:
                items.append({"role": "assistant", "content": m.text})
            for c in m.tool_calls:
                items.append({"type": "function_call", "call_id": safe_id(c.id), "name": c.name,
                              "arguments": json.dumps(c.arguments, ensure_ascii=False)})
        else:  # tool results
            for r in m.parts:
                if isinstance(r, ToolResult):
                    out = f"[tool error] {r.content}" if r.is_error else r.content
                    items.append({"type": "function_call_output", "call_id": safe_id(r.call_id), "output": out})
    return items


def _dump(item) -> dict:
    return item if isinstance(item, dict) else item.model_dump(mode="json", exclude_none=True)


def from_response(resp, requested_model: str) -> tuple[Message, str]:
    """(assistant message, stop_reason) from a Response. Raises ProviderError(malformed=True) when a
    function call's arguments aren't a JSON object."""
    parts: list = []
    refused = False
    for item in resp.output:
        kind = getattr(item, "type", None)
        if kind == "message":
            for c in item.content:
                if getattr(c, "type", None) == "output_text" and c.text:
                    parts.append(TextPart(c.text))
                elif getattr(c, "type", None) == "refusal":
                    refused = True
        elif kind == "function_call":
            try:
                args = json.loads(item.arguments or "{}")
            except ValueError as e:
                raise ProviderError("openai", f"unparsable tool arguments for {item.name}: {type(e).__name__}",
                                    malformed=True) from e
            if not isinstance(args, dict):
                raise ProviderError("openai", f"tool arguments for {item.name} are not an object", malformed=True)
            parts.append(ToolCall(id=item.call_id, name=item.name, arguments=args))
    state = {"openai": {"items": [_dump(it) for it in resp.output], "response_id": resp.id}}
    message = Message("assistant", parts, provider_state=state)
    if any(isinstance(p, ToolCall) for p in parts):
        stop = "tool_use"
    elif refused:
        stop = "refusal"
    elif getattr(resp, "status", None) == "incomplete" and \
            getattr(getattr(resp, "incomplete_details", None), "reason", None) == "max_output_tokens":
        stop = "max_tokens"
    else:
        stop = "end_turn"
    return message, stop


def usage_of(resp) -> Usage:
    u = getattr(resp, "usage", None)
    if u is None:
        return Usage()
    details = getattr(u, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) or 0
    written = getattr(details, "cache_write_tokens", 0) or 0
    # OpenAI's input_tokens includes the cached part; the canonical `input` is the uncached remainder
    return Usage(input=max((u.input_tokens or 0) - cached - written, 0), output=u.output_tokens or 0,
                 cache_read=cached, cache_write=written)


def classify(e: Exception) -> ProviderError:
    import openai
    if isinstance(e, ProviderError):
        return e
    if isinstance(e, (openai.APITimeoutError, openai.APIConnectionError)):
        return ProviderError("openai", f"{type(e).__name__}", retryable=True)
    if isinstance(e, openai.APIStatusError):
        status = e.status_code
        return ProviderError("openai", f"{type(e).__name__} (HTTP {status})", status=status,
                             retryable=status in RETRYABLE_STATUS or status >= 500)
    return ProviderError("openai", f"{type(e).__name__}", retryable=False)


class OpenAIProvider:
    name = "openai"

    def __init__(self, client=None, prices: dict | None = None):
        """`client`: an openai.OpenAI (made lazily from OPENAI_API_KEY when omitted; the SDK's own
        retry is capped at one so the router controls retries). `prices`: llm.<role>.prices_per_mtok."""
        self._client, self.prices = client, prices or {}

    def client(self):
        if self._client is None:
            import openai
            self._client = openai.OpenAI(max_retries=1)
        return self._client

    def complete(self, *, model: str, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec],
                 max_tokens: int, effort: Effort, timeout_s: float,
                 tool_choice: Literal["auto", "required"] | str = "auto") -> Completion:
        choice = tool_choice if tool_choice in ("auto", "required") else {"type": "function", "name": tool_choice}
        t0 = time.perf_counter()
        try:
            resp = self.client().responses.create(
                model=model, instructions=system, input=to_input(messages), tools=[tool_param(t) for t in tools],
                tool_choice=choice, parallel_tool_calls=True, max_output_tokens=max_tokens,
                reasoning={"effort": effort}, store=False, include=["reasoning.encrypted_content"],
                timeout=timeout_s)
        except Exception as e:
            raise classify(e) from e
        if getattr(resp, "status", None) == "failed":
            err = getattr(resp, "error", None)
            raise ProviderError("openai", f"response failed: {getattr(err, 'code', 'unknown')}", retryable=True)
        message, stop = from_response(resp, model)
        usage = usage_of(resp)
        return Completion(message=message, stop_reason=stop, usage=usage, provider=self.name,
                          model=resp.model or model, requested_model=model, duration_s=round(time.perf_counter() - t0, 3),
                          cost_usd=pricing.cost_usd(usage, self.prices), raw_id=resp.id)
