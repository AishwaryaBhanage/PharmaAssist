"""Anthropic on the Messages API (beta client), translated to and from the canonical format.

What v1's loop did, kept here: `effort` -> output_config.effort (thinking can't be turned off on
Sonnet 5.5, so effort is the latency lever), top-level ephemeral cache_control (caches the system
prompt, the tools and the conversation prefix automatically), `strict` tools, a refusal stop reason
-> "refusal", and the optional server-side refusal fallback beta (`fallbacks="default"`), which lets
an eligible Claude model answer a question Sonnet declined; the serving model is reported in
`Completion.model`, so the trace still shows who answered.

The assistant's own content blocks (thinking blocks included, with their signatures) are carried in
`Message.provider_state["anthropic"]` and re-sent verbatim; an assistant turn from another provider
is rebuilt from its canonical parts. Consecutive user-role messages (tool results followed by a
budget note) are merged into one user turn, as the API requires alternation.
"""

from __future__ import annotations

import time
from typing import Literal, Sequence

from pharmassist.llm import pricing
from pharmassist.llm.base import (Completion, Effort, Message, ProviderError, TextPart, ToolCall, ToolResult,
                                  ToolSpec, Usage)
from pharmassist.llm.openai_provider import safe_id

FALLBACK_BETA = "server-side-fallback-2026-07-01"
RETRYABLE_STATUS = {408, 409, 429, 529}
STOP = {"end_turn": "end_turn", "tool_use": "tool_use", "max_tokens": "max_tokens", "refusal": "refusal"}


def tool_param(t: ToolSpec) -> dict:
    out = {"name": t.name, "description": t.description, "input_schema": t.input_schema}
    if t.strict:
        out["strict"] = True
    return out


def _user_blocks(m: Message) -> list[dict]:
    blocks = []
    for p in m.parts:
        if isinstance(p, TextPart):
            blocks.append({"type": "text", "text": p.text})
        elif isinstance(p, ToolResult):
            blocks.append({"type": "tool_result", "tool_use_id": safe_id(p.call_id), "content": p.content,
                           "is_error": bool(p.is_error)})
    return blocks


def to_messages(messages: Sequence[Message]) -> list[dict]:
    """Canonical messages -> Messages API turns, consecutive user turns merged."""
    out: list[dict] = []
    for m in messages:
        if m.role == "assistant":
            own = (m.provider_state or {}).get("anthropic")
            if own and own.get("content"):
                content = own["content"]
            else:
                content = [{"type": "text", "text": p.text} if isinstance(p, TextPart) else
                           {"type": "tool_use", "id": safe_id(p.id), "name": p.name, "input": p.arguments}
                           for p in m.parts if isinstance(p, (TextPart, ToolCall))]
            out.append({"role": "assistant", "content": content})
            continue
        blocks = _user_blocks(m)
        if out and out[-1]["role"] == "user":
            out[-1]["content"] = list(out[-1]["content"]) + blocks
        else:
            out.append({"role": "user", "content": blocks})
    return out


def _dump(block) -> dict:
    return block if isinstance(block, dict) else block.model_dump(mode="json", exclude_none=True)


def from_response(resp) -> tuple[Message, str]:
    parts: list = []
    for b in resp.content:
        kind = getattr(b, "type", None)
        if kind == "text" and b.text:
            parts.append(TextPart(b.text))
        elif kind == "tool_use":
            if not isinstance(b.input, dict):
                raise ProviderError("anthropic", f"tool input for {b.name} is not an object", malformed=True)
            parts.append(ToolCall(id=b.id, name=b.name, arguments=dict(b.input)))
    state = {"anthropic": {"content": [_dump(b) for b in resp.content], "message_id": getattr(resp, "id", None)}}
    return Message("assistant", parts, provider_state=state), STOP.get(resp.stop_reason, "end_turn")


def usage_of(resp) -> Usage:
    u = resp.usage
    return Usage(input=u.input_tokens or 0, output=u.output_tokens or 0,
                 cache_read=getattr(u, "cache_read_input_tokens", None) or 0,
                 cache_write=getattr(u, "cache_creation_input_tokens", None) or 0)


def served_by_fallback(resp) -> bool:
    """The refusal-fallback beta answered on a substitute model."""
    return any(getattr(it, "type", None) == "fallback_message"
               for it in (getattr(resp.usage, "iterations", None) or []))


def classify(e: Exception) -> ProviderError:
    import anthropic
    if isinstance(e, ProviderError):
        return e
    if isinstance(e, (anthropic.APITimeoutError, anthropic.APIConnectionError)):
        return ProviderError("anthropic", f"{type(e).__name__}", retryable=True)
    if isinstance(e, anthropic.APIStatusError):
        status = e.status_code
        return ProviderError("anthropic", f"{type(e).__name__} (HTTP {status})", status=status,
                             retryable=status in RETRYABLE_STATUS or status >= 500)
    return ProviderError("anthropic", f"{type(e).__name__}", retryable=False)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client=None, prices: dict | None = None, refusal_fallback: bool = False):
        """`client`: an anthropic.Anthropic (made lazily from ANTHROPIC_API_KEY, with the workspace
        header when ANTHROPIC_WORKSPACE_ID is set). `refusal_fallback`: llm.fallback.refusal_fallback."""
        self._client, self.prices, self.refusal_fallback = client, prices or {}, refusal_fallback

    def client(self):
        if self._client is None:
            import os
            import anthropic
            workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
            headers = {"anthropic-workspace-id": workspace} if workspace else None
            self._client = anthropic.Anthropic(max_retries=1, default_headers=headers)
        return self._client

    def complete(self, *, model: str, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec],
                 max_tokens: int, effort: Effort, timeout_s: float,
                 tool_choice: Literal["auto", "required"] | str = "auto") -> Completion:
        params = {"model": model, "max_tokens": max_tokens, "system": system, "tools": [tool_param(t) for t in tools],
                  "output_config": {"effort": effort}, "cache_control": {"type": "ephemeral"},
                  "messages": to_messages(messages), "timeout": max(1.0, float(timeout_s))}
        if tool_choice == "required":
            params["tool_choice"] = {"type": "any"}
        elif tool_choice != "auto":
            params["tool_choice"] = {"type": "tool", "name": tool_choice}
        if self.refusal_fallback:
            params.update(betas=[FALLBACK_BETA], fallbacks="default")
        t0 = time.perf_counter()
        try:
            resp = self.client().beta.messages.create(**params)
        except Exception as e:
            raise classify(e) from e
        message, stop = from_response(resp)
        message.provider_state["anthropic"]["refusal_fallback"] = served_by_fallback(resp)
        usage = usage_of(resp)
        # a refusal-fallback hop answers on another Claude model; `model` names it, the price table is Sonnet's
        return Completion(message=message, stop_reason=stop, usage=usage, provider=self.name,
                          model=resp.model or model, requested_model=model, duration_s=round(time.perf_counter() - t0, 3),
                          cost_usd=pricing.cost_usd(usage, self.prices), raw_id=getattr(resp, "id", None))
