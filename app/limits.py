"""Usage limits for /ask (config `limits_v2`), counted per authenticated user and globally:

- per user: questions per minute and per day, keyed by a salted hash of the user id (the raw id is
  never a Redis key);
- global: questions per day and model spend (USD) per day across all users and instances.

admit() reserves an estimated cost before the model is called, so concurrent questions can't
overshoot the spend cap; settle() replaces the estimate with the measured cost afterwards. Two
backends: in-memory (one process, tests) and Redis/Valkey (shared by every instance, atomic
INCR/INCRBYFLOAT, expired by TTL). The Redis guard fails closed: a Redis error propagates and the
API answers 503 `limits_unavailable` rather than spending without limits. Days are UTC.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

MINUTE_TTL, DAY_TTL, TOTAL_TTL = 120, 2 * 86400, 35 * 86400


@dataclass(frozen=True)
class Limits:
    per_user_per_minute: int = 10
    per_user_per_day: int = 100
    questions_per_day: int = 500
    spend_usd_per_day: float = 10.0
    estimate_usd: float = 0.08     # reserved per question until its real cost is known

    @classmethod
    def from_config(cls, cfg: dict | None) -> "Limits":
        cfg = dict(cfg or {})
        for k in cls.__dataclass_fields__:  # LIMIT_<NAME> environment variables override config.yaml
            env = os.environ.get(f"LIMIT_{k.upper()}")
            if env:
                cfg[k] = float(env) if "usd" in k else int(env)
        return cls(**{k: v for k, v in cfg.items() if k in cls.__dataclass_fields__})


class Refused(Exception):
    def __init__(self, code: str, message: str, retry_after: int):
        super().__init__(code)
        self.code, self.message, self.retry_after = code, message, retry_after


def user_key(user_id: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}|{user_id}".encode()).hexdigest()[:20]


def _day(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")


def _seconds_to_midnight(now: float) -> int:
    return int(86400 - now % 86400) + 1


class _Base:
    limits: Limits
    salt: str

    def _check(self, now: float, minute_n, day_n, q_n, spend) -> None:
        L = self.limits
        if minute_n > L.per_user_per_minute:
            raise Refused("rate_limited", "Too many questions in a minute. Please wait a moment.",
                          int(60 - now % 60) + 1)
        if day_n > L.per_user_per_day:
            raise Refused("daily_limit", "You have reached today's question limit. Try again tomorrow.",
                          _seconds_to_midnight(now))
        if q_n > L.questions_per_day:
            raise Refused("daily_limit", "The assistant's daily question limit has been reached. Try again tomorrow.",
                          _seconds_to_midnight(now))
        if spend > L.spend_usd_per_day:
            raise Refused("spend_cap", "The assistant's daily spend cap has been reached. Try again tomorrow.",
                          _seconds_to_midnight(now))

    def _keys(self, user_id: str, now: float) -> tuple[str, str, str, str]:
        k, day, minute = user_key(user_id, self.salt), _day(now), int(now // 60)
        return f"pa:lim:u:{k}:m:{minute}", f"pa:lim:u:{k}:d:{day}", f"pa:lim:g:q:{day}", f"pa:lim:g:s:{day}"


class MemoryGuard(_Base):
    def __init__(self, limits: Limits, salt: str | None = None, clock=time.time):
        self.limits, self.salt, self.clock = limits, salt or os.urandom(16).hex(), clock
        self._lock = threading.Lock()
        self._counts: dict[str, float] = {}

    def _add(self, key: str, n: float) -> float:
        self._counts[key] = self._counts.get(key, 0) + n
        return self._counts[key]

    def admit(self, user_id: str) -> None:
        now = self.clock()
        mk, dk, qk, sk = self._keys(user_id, now)
        with self._lock:
            counts = (self._add(mk, 1), self._add(dk, 1), self._add(qk, 1),
                      self._add(sk, self.limits.estimate_usd))
            try:
                self._check(now, *counts)
            except Refused:
                for key, n in ((mk, 1), (dk, 1), (qk, 1), (sk, self.limits.estimate_usd)):
                    self._add(key, -n)
                raise

    def settle(self, user_id: str, cost_usd: float | None) -> None:
        _, _, _, sk = self._keys(user_id, self.clock())
        with self._lock:
            self._add(sk, (cost_usd or 0) - self.limits.estimate_usd)

    def usage(self) -> dict:
        now = self.clock()
        _, _, qk, sk = self._keys("", now)
        return {"day": _day(now), "questions": int(self._counts.get(qk, 0)),
                "spend_usd": round(max(self._counts.get(sk, 0), 0.0), 4),
                "spend_cap_usd": self.limits.spend_usd_per_day}

    def ping(self) -> bool:
        return True


class RedisGuard(_Base):
    """Counters in Redis/Valkey. Every admit is one MULTI/EXEC pipeline, so the increments are atomic
    across instances; a refused question is rolled back the same way."""

    def __init__(self, client, limits: Limits, salt: str, clock=time.time):
        self.r, self.limits, self.salt, self.clock = client, limits, salt, clock

    def admit(self, user_id: str) -> None:
        now = self.clock()
        mk, dk, qk, sk = self._keys(user_id, now)
        p = self.r.pipeline(transaction=True)
        p.incr(mk); p.expire(mk, MINUTE_TTL)
        p.incr(dk); p.expire(dk, DAY_TTL)
        p.incr(qk); p.expire(qk, TOTAL_TTL)
        p.incrbyfloat(sk, self.limits.estimate_usd); p.expire(sk, TOTAL_TTL)
        res = p.execute()
        minute_n, day_n, q_n, spend = int(res[0]), int(res[2]), int(res[4]), float(res[6])
        try:
            self._check(now, minute_n, day_n, q_n, spend)
        except Refused:
            p = self.r.pipeline(transaction=True)
            p.decr(mk); p.decr(dk); p.decr(qk); p.incrbyfloat(sk, -self.limits.estimate_usd)
            p.execute()
            raise

    def settle(self, user_id: str, cost_usd: float | None) -> None:
        _, _, _, sk = self._keys(user_id, self.clock())
        p = self.r.pipeline(transaction=True)
        p.incrbyfloat(sk, round((cost_usd or 0) - self.limits.estimate_usd, 6)); p.expire(sk, TOTAL_TTL)
        p.execute()

    def usage(self) -> dict:
        now = self.clock()
        _, _, qk, sk = self._keys("", now)
        q, s = self.r.mget(qk, sk)
        return {"day": _day(now), "questions": int(q or 0), "spend_usd": round(max(float(s or 0), 0.0), 4),
                "spend_cap_usd": self.limits.spend_usd_per_day}

    def ping(self) -> bool:
        try:
            return bool(self.r.ping())
        except Exception:
            return False
