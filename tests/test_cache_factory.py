"""open_cache(): config → implementation, and never raising because the server is down."""

import logging

import numpy as np

from pharmassist.cache import open_cache
from pharmassist.cache.base import NullCache
from pharmassist.cache.memory import MemoryCache
from pharmassist.cache.valkey import ValkeyCache
from test_cache_support import DIM, entry

BLOCK = {"enabled": True, "backend": "valkey", "url_env": "REDIS_URL", "threshold": 0.9, "max_entries": 20000,
         "ttl_days": 30, "index_name": "pa_answers"}


def test_disabled_or_null_backend_is_null_cache():
    assert isinstance(open_cache({"cache": {**BLOCK, "enabled": False}}), NullCache)
    assert isinstance(open_cache({"cache": {**BLOCK, "backend": None}}), NullCache)
    assert isinstance(open_cache({**BLOCK, "backend": "null"}), NullCache)


def test_memory_backend_takes_settings():
    c = open_cache({"cache": {**BLOCK, "backend": "memory", "threshold": 0.95, "max_entries": 5}})
    assert isinstance(c, MemoryCache) and c.threshold == 0.95 and c.max_entries == 5
    v = np.ones(DIM)
    c.put(entry(), v)
    assert c.lookup(v, 1) is not None


def test_valkey_backend_down_does_not_raise(monkeypatch, caplog):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    with caplog.at_level(logging.WARNING, logger="pharmassist.cache"):
        c = open_cache({"cache": BLOCK})
    assert isinstance(c, ValkeyCache) and c.ping() is False
    assert c.lookup(np.ones(DIM), 1) is None
    assert any("unreachable" in r.message for r in caplog.records)


def test_valkey_backend_without_url_env_falls_back_to_localhost(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr("pharmassist.cache.factory._load_dotenv_once", lambda: None)
    c = open_cache({"cache": {**BLOCK, "url_env": "PA_UNSET_CACHE_URL"}})
    assert isinstance(c, ValkeyCache) and c.url == "redis://localhost:6379/0"


def test_config_yaml_block_builds(monkeypatch):
    """The checked-in config.yaml's cache block is valid for the factory (whatever server is around)."""
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setattr("pharmassist.cache.factory._load_dotenv_once", lambda: None)
    assert open_cache().name in ("valkey", "memory", "null")
