"""The LLM contract (v2). The agent loop builds `Message`s in this canonical format and calls
`Router.complete()`; providers translate to and from their own APIs.

Canonical conversation shape (what `complete()` receives in `messages`):
    user:      [TextPart]
    assistant: [TextPart?, ToolCall*]          (what a provider returned, re-sent verbatim next turn)
    tool:      [ToolResult+]                   (one message carrying the results of the previous turn's calls)
    system text is passed separately as `system`; a mid-conversation note (v1's BUDGET_SPENT) is a
    user message, since OpenAI has no system-role turn mid-thread and Anthropic has none at all.

Provider mapping (stream B):
    OpenAI    Responses API; tools = function tools with `strict` honoured; reasoning effort from
              `effort`; the assistant's reasoning items are carried in `Message.provider_state` and
              re-sent, so a thread started on OpenAI continues on OpenAI without loss.
    Anthropic Messages API; `effort` → output_config.effort; `strict` → the tool's strict flag;
              prompt caching on the system prompt and tools.
A thread may switch provider only at a turn boundary (after a `tool` message or at the start); the
router does this on failure. Tool call ids are the provider's; when the router falls back
mid-thread it re-issues ids, so providers must not assume a format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, Sequence

StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal"]
Effort = Literal["low", "medium", "high"]


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict               # JSON Schema (object)
    strict: bool = False             # the provider must enforce the schema exactly (submit_answer)


@dataclass
class TextPart:
    text: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict                  # parsed JSON; a provider raises ProviderError(malformed=True) if it can't parse


@dataclass
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    parts: list[TextPart | ToolCall | ToolResult]
    provider_state: dict | None = None   # opaque provider items to re-send (OpenAI reasoning items, etc.)

    @property
    def text(self) -> str:
        return "".join(p.text for p in self.parts if isinstance(p, TextPart))

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [p for p in self.parts if isinstance(p, ToolCall)]


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    def __add__(self, o: "Usage") -> "Usage":
        return Usage(self.input + o.input, self.output + o.output, self.cache_read + o.cache_read,
                     self.cache_write + o.cache_write)


@dataclass
class Completion:
    message: Message                 # role == "assistant"
    stop_reason: StopReason
    usage: Usage
    provider: str                    # "openai" | "anthropic"
    model: str                       # the model that actually answered
    requested_model: str
    fallback_used: bool = False      # this call was served by the fallback
    duration_s: float = 0.0
    cost_usd: float = 0.0            # priced at the serving model's rates (config llm.*.prices_per_mtok)
    raw_id: str | None = None        # provider response id, for debugging


class LLMError(Exception):
    """Base for everything raised by this package."""


class ProviderError(LLMError):
    """A call failed. `retryable`: a transport error, timeout, 429 or 5xx (the router may retry and then
    fall back). `malformed`: the provider returned an unparsable tool call (also triggers fallback).
    Neither retryable nor malformed (400 bad request, auth): the router falls back once, then raises."""

    def __init__(self, provider: str, message: str, *, status: int | None = None, retryable: bool = False,
                 malformed: bool = False):
        super().__init__(f"{provider}: {message}")
        self.provider, self.status, self.retryable, self.malformed = provider, status, retryable, malformed


class AllProvidersFailed(LLMError):
    def __init__(self, errors: list[ProviderError]):
        super().__init__("; ".join(str(e) for e in errors))
        self.errors = errors


class Provider(Protocol):
    name: str

    def complete(self, *, model: str, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec],
                 max_tokens: int, effort: Effort, timeout_s: float,
                 tool_choice: Literal["auto", "required"] | str = "auto") -> Completion:
        """One model call. `tool_choice` may name a tool to force. Never retries internally beyond the
        SDK's own single retry; never logs message content."""


class Router(Protocol):
    """`complete()` with the primary provider; on ProviderError it retries per `llm.retry`, then runs
    the same call on the fallback and marks `fallback_used`. Once a thread has fallen back, the
    caller keeps passing `prefer=` the serving provider so the rest of the turn stays there."""

    def complete(self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec],
                 timeout_s: float, prefer: str | None = None,
                 tool_choice: Literal["auto", "required"] | str = "auto") -> Completion: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Query/document embeddings (llm.embedding): OpenAI text-embedding-3-large, 3,072 dims."""
