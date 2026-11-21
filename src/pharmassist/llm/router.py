"""The Router: OpenAI first, Anthropic when OpenAI can't answer, one call at a time.

Per `complete()`: the primary gets `llm.retry.attempts` tries on a retryable error (transport,
timeout, 429, 5xx) with exponential backoff; a non-retryable error (400, auth) or a malformed tool
call skips the retries. Then the fallback runs the same call once, marked `fallback_used`. Both
failing raises AllProvidersFailed with every error. `prefer=` names the provider that served the
previous call of a thread, so a turn that fell back stays on the fallback (OpenAI reasoning items
aren't re-sent to Anthropic and vice versa; each provider rebuilds foreign assistant turns from the
canonical parts, so switching is safe at any turn boundary, but a thread shouldn't ping-pong).

Thread safety: the router holds no per-call state; the SDK clients are thread-safe, so the API's
worker pool shares one instance. `embed()` goes to OpenAI text-embedding-3-large and enforces the
configured dimension, since the cache and pgvector both depend on it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal, Sequence

from pharmassist.llm.base import AllProvidersFailed, Completion, Message, Provider, ProviderError, ToolSpec


@dataclass
class Role:
    """One configured model: `llm.primary` or `llm.fallback`."""
    provider: Provider
    model: str
    effort: str = "medium"
    max_tokens: int = 4096
    prices: dict = field(default_factory=dict)


class Router:
    def __init__(self, primary: Role, fallback: Role | None = None, *, attempts: int = 2, backoff_s: float = 0.8,
                 embed_client=None, embedding_model: str = "text-embedding-3-large", embedding_dim: int = 3072,
                 embedding_timeout_s: float = 20.0, sleep=time.sleep):
        self.primary, self.fallback = primary, fallback
        self.attempts, self.backoff_s, self.sleep = max(1, int(attempts)), float(backoff_s), sleep
        self._embed_client, self.embedding_model = embed_client, embedding_model
        self.embedding_dim, self.embedding_timeout_s = int(embedding_dim), float(embedding_timeout_s)

    @property
    def providers(self) -> list[str]:
        return [r.provider.name for r in (self.primary, self.fallback) if r is not None]

    def _call(self, role: Role, fallback_used: bool, **kw) -> Completion:
        c = role.provider.complete(model=role.model, effort=role.effort, max_tokens=role.max_tokens, **kw)
        c.fallback_used = fallback_used
        return c

    def complete(self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec],
                 timeout_s: float, prefer: str | None = None,
                 tool_choice: Literal["auto", "required"] | str = "auto") -> Completion:
        kw = dict(system=system, messages=messages, tools=tools, timeout_s=timeout_s, tool_choice=tool_choice)
        errors: list[ProviderError] = []
        if self.fallback is not None and prefer == self.fallback.provider.name:
            # the thread already fell back: stay there rather than retrying the primary mid-thread
            try:
                return self._call(self.fallback, True, **kw)
            except ProviderError as e:
                raise AllProvidersFailed([e]) from e
        for attempt in range(self.attempts):
            try:
                return self._call(self.primary, False, **kw)
            except ProviderError as e:
                errors.append(e)
                if not e.retryable or attempt == self.attempts - 1:
                    break
                self.sleep(self.backoff_s * (2 ** attempt))
        if self.fallback is None:
            raise AllProvidersFailed(errors)
        try:
            return self._call(self.fallback, True, **kw)
        except ProviderError as e:
            errors.append(e)
            raise AllProvidersFailed(errors) from e

    # ---- embeddings ----
    def embed_client(self):
        if self._embed_client is None:
            import openai
            self._embed_client = openai.OpenAI(max_retries=2)
        return self._embed_client

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embeddings in input order; raises ProviderError on an API failure or a wrong dimension."""
        texts = list(texts)
        if not texts:
            return []
        try:
            resp = self.embed_client().embeddings.create(model=self.embedding_model, input=texts,
                                                         dimensions=self.embedding_dim, timeout=self.embedding_timeout_s)
        except Exception as e:
            from pharmassist.llm.openai_provider import classify
            raise classify(e) from e
        out = [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
        if len(out) != len(texts) or any(len(v) != self.embedding_dim for v in out):
            raise ProviderError("openai", f"embedding response has the wrong shape (expected {len(texts)} x "
                                          f"{self.embedding_dim})")
        return out


def _role(block: dict, provider: Provider) -> Role:
    return Role(provider=provider, model=block["model"], effort=block.get("effort", "medium"),
                max_tokens=int(block.get("max_tokens", 4096)), prices=block.get("prices_per_mtok") or {})


def _provider(block: dict, clients: dict) -> Provider:
    name = block.get("provider", "openai")
    if name == "openai":
        from pharmassist.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(client=clients.get("openai"), prices=block.get("prices_per_mtok"))
    if name == "anthropic":
        from pharmassist.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(client=clients.get("anthropic"), prices=block.get("prices_per_mtok"),
                                 refusal_fallback=bool(block.get("refusal_fallback", False)))
    raise ValueError(f"unknown LLM provider {name!r}")


def router_from_config(cfg: dict, *, clients: dict | None = None, sleep=time.sleep) -> Router:
    """A Router from config.yaml's `llm:` block (pass the whole config or just that block). `clients`
    may inject SDK clients by provider name ({"openai": ..., "anthropic": ...}) for tests; otherwise
    they are built lazily from the environment (.env must already be loaded)."""
    llm = cfg.get("llm", cfg)
    clients = clients or {}
    primary = _role(llm["primary"], _provider(llm["primary"], clients))
    fallback = _role(llm["fallback"], _provider(llm["fallback"], clients)) if llm.get("fallback") else None
    retry, emb = llm.get("retry") or {}, llm.get("embedding") or {}
    return Router(primary, fallback, attempts=retry.get("attempts", 2), backoff_s=retry.get("backoff_s", 0.8),
                  embed_client=clients.get("openai_embeddings") or clients.get("openai"),
                  embedding_model=emb.get("model", "text-embedding-3-large"), embedding_dim=emb.get("dimension", 3072),
                  embedding_timeout_s=emb.get("timeout_s", 20), sleep=sleep)
