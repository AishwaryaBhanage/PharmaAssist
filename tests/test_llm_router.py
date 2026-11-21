"""The Router over fake providers: retries, fallback, prefer, AllProvidersFailed, config, embeddings."""

from types import SimpleNamespace as NS

import pytest

from pharmassist.llm.base import AllProvidersFailed, Message, ProviderError, TextPart
from pharmassist.llm.router import Role, Router, router_from_config
from tests.test_agent_fakes import CFG, FakeProvider, error, make_router, reply, text

MSG = [Message("user", [TextPart("q")])]


def call(router, prefer=None):
    return router.complete(system="S", messages=MSG, tools=[], timeout_s=10, prefer=prefer)


def test_primary_answers_and_is_not_marked_as_fallback():
    r = make_router(reply(text("hi")))
    c = call(r)
    assert (c.provider, c.model, c.fallback_used) == ("openai", "gpt-5.5", False)
    assert r.fake_primary.requests[0]["model"] == "gpt-5.5" and r.fake_primary.requests[0]["effort"] == "medium"
    assert r.fake_fallback.requests == []


def test_a_429_is_retried_on_the_primary_with_backoff_then_succeeds():
    slept = []
    r = make_router(error(429, retryable=True), reply(text("ok")))
    r.sleep, r.backoff_s = slept.append, 0.8
    c = call(r)
    assert c.provider == "openai" and c.fallback_used is False and len(r.fake_primary.requests) == 2
    assert slept == [0.8]


def test_500s_exhaust_the_retries_then_the_fallback_serves_once():
    r = make_router(error(500, retryable=True), error(503, retryable=True), fallback_script=[reply(text("sonnet"))])
    c = call(r)
    assert (c.provider, c.model, c.fallback_used) == ("anthropic", "claude-sonnet-5-5", True)
    assert len(r.fake_primary.requests) == 2 and len(r.fake_fallback.requests) == 1
    # the fallback gets the same call: system, messages and tools untouched
    assert r.fake_fallback.requests[0]["system"] == "S" and r.fake_fallback.requests[0]["messages"] == MSG


def test_a_malformed_tool_call_falls_back_without_retrying():
    r = make_router(error(malformed=True), fallback_script=[reply(text("sonnet"))])
    c = call(r)
    assert c.fallback_used and len(r.fake_primary.requests) == 1


def test_a_non_retryable_primary_error_falls_back_once():
    r = make_router(error(400), fallback_script=[reply(text("sonnet"))])
    assert call(r).fallback_used and len(r.fake_primary.requests) == 1


def test_both_failing_raises_all_providers_failed_with_every_error():
    r = make_router(error(429, retryable=True), error(500, retryable=True), fallback_script=[error(529, retryable=True)])
    with pytest.raises(AllProvidersFailed) as e:
        call(r)
    assert [x.status for x in e.value.errors] == [429, 500, 529]
    assert "scripted failure 429" in str(e.value) and "529" in str(e.value)


def test_prefer_keeps_a_thread_on_the_fallback_without_touching_the_primary():
    r = make_router(reply(text("never used")), fallback_script=[reply(text("sonnet again"))])
    c = call(r, prefer="anthropic")
    assert c.provider == "anthropic" and c.fallback_used is True and r.fake_primary.requests == []


def test_prefer_fallback_failing_raises_without_retrying_the_primary():
    r = make_router(reply(text("x")), fallback_script=[error(500, retryable=True)])
    with pytest.raises(AllProvidersFailed):
        call(r, prefer="anthropic")
    assert r.fake_primary.requests == []


def test_prefer_primary_is_the_normal_order():
    r = make_router(reply(text("hi")))
    assert call(r, prefer="openai").provider == "openai"


def test_no_fallback_configured_raises_after_the_retries():
    p = FakeProvider("openai", error(500, retryable=True), error(500, retryable=True))
    r = Router(Role(p, "gpt-5.5"), None, attempts=2, backoff_s=0, sleep=lambda s: None)
    with pytest.raises(AllProvidersFailed) as e:
        call(r)
    assert len(e.value.errors) == 2


def test_attempts_one_means_no_retry():
    r = make_router(error(429, retryable=True), fallback_script=[reply(text("s"))], attempts=1)
    assert call(r).fallback_used and len(r.fake_primary.requests) == 1


def test_router_is_safe_to_share_across_threads():
    from concurrent.futures import ThreadPoolExecutor
    n = 20
    r = make_router(*[reply(text(f"r{i}")) for i in range(n)])
    with ThreadPoolExecutor(8) as pool:
        out = list(pool.map(lambda _: call(r).provider, range(n)))
    assert out == ["openai"] * n and len(r.fake_primary.requests) == n


# ---- from config ----

def test_router_from_config_builds_both_roles_and_retry_settings():
    r = router_from_config(CFG, clients={"openai": NS(), "anthropic": NS()})
    assert r.providers == ["openai", "anthropic"] and r.primary.model == "gpt-5.5" and r.fallback.model == "claude-sonnet-5-5"
    assert r.attempts == 2 and r.primary.prices == CFG["llm"]["primary"]["prices_per_mtok"]
    assert r.fallback.provider.refusal_fallback is False and r.embedding_dim == 3072
    cfg = {"llm": {**CFG["llm"], "fallback": {**CFG["llm"]["fallback"], "refusal_fallback": True}}}
    assert router_from_config(cfg, clients={}).fallback.provider.refusal_fallback is True


def test_the_project_config_has_real_prices_for_the_primary():
    from pharmassist.config import load_config
    llm = load_config()["llm"]
    assert llm["primary"]["model"] == "gpt-5.5"
    assert llm["primary"]["prices_per_mtok"] == {"input": 5.0, "output": 30.0, "cache_read": 0.5, "cache_write": 0}
    assert llm["fallback"]["prices_per_mtok"]["input"] == 2.0
    r = router_from_config(load_config(), clients={"openai": NS(), "anthropic": NS()})
    assert r.fallback.provider.refusal_fallback is True


# ---- embeddings ----

class EmbedClient:
    def __init__(self, dim=3072, drop=False):
        self.dim, self.drop, self.calls = dim, drop, []
        self.embeddings = NS(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        data = [NS(index=i, embedding=[float(i)] * self.dim) for i in range(len(kw["input"]))]
        if self.drop:
            data = data[1:]
        return NS(data=list(reversed(data)), model=kw["model"])


def test_embed_uses_text_embedding_3_large_at_3072_and_keeps_input_order():
    client = EmbedClient()
    r = Router(Role(FakeProvider("openai"), "m"), embed_client=client)
    out = r.embed(["a", "b"])
    assert client.calls[0]["model"] == "text-embedding-3-large" and client.calls[0]["dimensions"] == 3072
    assert [len(v) for v in out] == [3072, 3072] and out[0][0] == 0.0 and out[1][0] == 1.0
    assert r.embed([]) == [] and len(client.calls) == 1


def test_embed_enforces_the_dimension_and_the_count():
    with pytest.raises(ProviderError, match="wrong shape"):
        Router(Role(FakeProvider("openai"), "m"), embed_client=EmbedClient(dim=1536)).embed(["a"])
    with pytest.raises(ProviderError, match="wrong shape"):
        Router(Role(FakeProvider("openai"), "m"), embed_client=EmbedClient(drop=True)).embed(["a", "b"])


def test_embed_errors_are_provider_errors():
    import httpx
    import openai

    class Broken:
        embeddings = NS(create=lambda **kw: (_ for _ in ()).throw(
            openai.RateLimitError("r", response=httpx.Response(429, request=httpx.Request("POST", "https://x")), body=None)))
    with pytest.raises(ProviderError) as e:
        Router(Role(FakeProvider("openai"), "m"), embed_client=Broken()).embed(["a"])
    assert e.value.retryable and e.value.status == 429
