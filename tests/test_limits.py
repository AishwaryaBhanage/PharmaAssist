"""Usage limits: config loading with env overrides, the in-memory guard, the Redis guard against a
scripted fake client (atomic pipeline, rollback, fail-closed) and, when docker is available, against
a real Valkey container (`pytest -m integration`)."""

import shutil
import socket
import subprocess
import time

import pytest

from app.limits import Limits, MemoryGuard, RedisGuard, Refused, user_key

T0 = 1_800_000_000.0   # 2027-01-15T08:00:00Z


def test_limits_from_config_and_env(monkeypatch):
    L = Limits.from_config({"per_user_per_minute": 3, "spend_usd_per_day": 1.5, "unknown": 1})
    assert (L.per_user_per_minute, L.per_user_per_day, L.spend_usd_per_day, L.estimate_usd) == (3, 100, 1.5, 0.08)
    monkeypatch.setenv("LIMIT_PER_USER_PER_DAY", "7")
    monkeypatch.setenv("LIMIT_SPEND_USD_PER_DAY", "0.5")
    L = Limits.from_config({"per_user_per_day": 100})
    assert L.per_user_per_day == 7 and L.spend_usd_per_day == 0.5


def test_user_keys_are_salted_hashes():
    assert user_key("u1", "a") != user_key("u1", "b") and "u1" not in user_key("u1", "a") and len(user_key("u1", "a")) == 20


class FakeClock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def guard(**kw):
    clock = FakeClock()
    g = MemoryGuard(Limits(**{"per_user_per_minute": 2, "per_user_per_day": 3, "questions_per_day": 5,
                              "spend_usd_per_day": 0.25, "estimate_usd": 0.1, **kw}), salt="s", clock=clock)
    return g, clock


def test_memory_guard_per_minute_then_daily_per_user():
    g, clock = guard(spend_usd_per_day=100.0)
    g.admit("u1"); g.admit("u1")
    with pytest.raises(Refused) as e:
        g.admit("u1")
    assert e.value.code == "rate_limited" and 0 < e.value.retry_after <= 61
    g.admit("u2")                               # another user is unaffected
    clock.t += 60
    g.admit("u1")                               # 3rd of the day
    with pytest.raises(Refused) as e:
        clock.t += 60
        g.admit("u1")
    assert e.value.code == "daily_limit" and e.value.retry_after <= 86401
    assert g.usage()["questions"] == 4         # refused questions are rolled back


def test_memory_guard_global_question_cap_and_spend_cap():
    g, clock = guard()
    for i in range(5):
        g.admit(f"u{i}")
        g.settle(f"u{i}", 0.0)
    with pytest.raises(Refused) as e:
        g.admit("u9")
    assert e.value.code == "daily_limit"
    g2, clock2 = guard()
    g2.admit("a"); g2.settle("a", 0.12)
    g2.admit("b"); g2.settle("b", 0.06)         # 0.18 spent; + 0.1 reserved > 0.25
    with pytest.raises(Refused) as e:
        g2.admit("c")
    assert e.value.code == "spend_cap"
    assert g2.usage() == {"day": "2027-01-15", "questions": 2, "spend_usd": 0.18, "spend_cap_usd": 0.25}
    clock2.t += 86400                            # a new UTC day
    g2.admit("c")
    assert g2.usage()["questions"] == 1


class FakeRedis:
    """Just enough of redis-py: a transactional pipeline over a dict, with an error switch."""
    def __init__(self):
        self.kv, self.ttl, self.down = {}, {}, False

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    def mget(self, *keys):
        if self.down:
            raise ConnectionError("down")
        return [self.kv.get(k) for k in keys]

    def ping(self):
        if self.down:
            raise ConnectionError("down")
        return True


class FakePipeline:
    def __init__(self, r):
        self.r, self.ops = r, []

    def incr(self, k): self.ops.append(("incr", k, 1))
    def decr(self, k): self.ops.append(("incr", k, -1))
    def incrbyfloat(self, k, n): self.ops.append(("incrf", k, n))
    def expire(self, k, s): self.ops.append(("expire", k, s))

    def execute(self):
        if self.r.down:
            raise ConnectionError("down")
        out = []
        for op, k, n in self.ops:
            if op == "incr":
                self.r.kv[k] = int(self.r.kv.get(k, 0)) + n
                out.append(self.r.kv[k])
            elif op == "incrf":
                self.r.kv[k] = float(self.r.kv.get(k, 0)) + n
                out.append(repr(self.r.kv[k]))
            else:
                self.r.ttl[k] = n
                out.append(True)
        return out


def test_redis_guard_counts_rolls_back_and_sets_ttls():
    r, clock = FakeRedis(), FakeClock()
    g = RedisGuard(r, Limits(per_user_per_minute=1, per_user_per_day=10, questions_per_day=10, spend_usd_per_day=1.0,
                             estimate_usd=0.1), salt="s", clock=clock)
    g.admit("u1")
    with pytest.raises(Refused):
        g.admit("u1")
    keys = sorted(r.kv)
    assert [k.split(":")[2] for k in keys] == ["g", "g", "u", "u"] and all("u1" not in k for k in keys)
    assert r.kv[f"pa:lim:g:q:2027-01-15"] == 1 and abs(r.kv["pa:lim:g:s:2027-01-15"] - 0.1) < 1e-9
    assert r.ttl["pa:lim:g:q:2027-01-15"] == 35 * 86400 and min(r.ttl.values()) == 120
    g.settle("u1", 0.03)
    assert g.usage() == {"day": "2027-01-15", "questions": 1, "spend_usd": 0.03, "spend_cap_usd": 1.0}


def test_redis_guard_fails_closed():
    r = FakeRedis()
    g = RedisGuard(r, Limits(), salt="s", clock=FakeClock())
    r.down = True
    with pytest.raises(ConnectionError):
        g.admit("u1")
    assert g.ping() is False


# ---------------------------------------------------------------- integration: a real Valkey

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def valkey_url():
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    port, name = _free_port(), f"pa-valkey-test-{_free_port()}"
    run = subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-p", f"127.0.0.1:{port}:6379", "valkey/valkey:8"],
                         capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        pytest.skip(f"docker could not start valkey: {run.stderr.strip()[:200]}")
    try:
        import redis
        client = redis.Redis(host="127.0.0.1", port=port, socket_connect_timeout=1, decode_responses=True)
        for _ in range(50):
            try:
                if client.ping():
                    break
            except redis.RedisError:
                time.sleep(0.2)
        else:
            pytest.skip("valkey did not become ready")
        yield f"redis://127.0.0.1:{port}/0"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)


@pytest.mark.integration
def test_redis_guard_against_valkey(valkey_url):
    import redis
    client = redis.Redis.from_url(valkey_url, socket_timeout=2, decode_responses=True)
    client.flushdb()
    clock = FakeClock()
    L = Limits(per_user_per_minute=2, per_user_per_day=100, questions_per_day=3, spend_usd_per_day=0.25, estimate_usd=0.1)
    a, b = RedisGuard(client, L, salt="s", clock=clock), RedisGuard(client, L, salt="s", clock=clock)  # two instances
    a.admit("u1"); b.admit("u1")
    with pytest.raises(Refused) as e:
        a.admit("u1")
    assert e.value.code == "rate_limited"
    a.settle("u1", 0.2); b.settle("u1", 0.0)
    with pytest.raises(Refused) as e:               # 0.2 spent + 0.1 reserved > 0.25
        b.admit("u2")
    assert e.value.code == "spend_cap"
    assert b.usage() == {"day": "2027-01-15", "questions": 2, "spend_usd": 0.2, "spend_cap_usd": 0.25}
    day = "2027-01-15"
    assert client.ttl(f"pa:lim:g:q:{day}") > 30 * 86400 and 0 < client.ttl(next(k for k in client.keys("pa:lim:u:*:m:*"))) <= 120
    assert not any("u1" in k for k in client.keys("pa:lim:*"))
    client.flushdb()
