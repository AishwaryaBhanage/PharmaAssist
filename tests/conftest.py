"""Shared test setup: LangSmith tracing is off in every test unless a test turns it on itself.

The developer's .env may set LANGSMITH_TRACING=true; load_dotenv never overrides a variable that's
already set, so setting it here keeps normal tests from sending anything to LangSmith.
"""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: needs docker (Valkey, Postgres); skipped when unavailable")


@pytest.fixture(autouse=True)
def no_langsmith(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_CONTENT_MODE", "metadata")
