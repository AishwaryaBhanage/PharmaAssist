"""Provider-independent LLM access (v2): OpenAI first, Anthropic as the fallback, one canonical
message and tool-call format. See `base` for the contract; stream B implements `openai_provider`,
`anthropic_provider` and `router`."""

from pharmassist.llm.base import (  # noqa: F401
    AllProvidersFailed, Completion, LLMError, Message, Provider, ProviderError, StopReason, TextPart, ToolCall,
    ToolResult, ToolSpec, Usage,
)
from pharmassist.llm.router import Router, router_from_config  # noqa: F401
