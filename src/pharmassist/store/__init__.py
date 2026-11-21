"""Persistent storage for v2: PostgreSQL (+pgvector) behind the protocols in `protocols`.

`pharmassist.store.pg` is the real store and `pharmassist.store.memory` an in-memory store with the
same behaviour, for other streams' unit tests. `open_store()` is the single entry point the app and
the worker use; `MemoryStore` is importable from here so tests need only this package.
"""

from pharmassist.store.memory import MemoryStore  # noqa: F401
from pharmassist.store.protocols import (NO_ANSWER_TEXT, ChunkRecord, Conflict, Conversation, Document,  # noqa: F401
                                         DocumentVersion, Feedback, FigureRecord, IngestionJob, Message, NotFound,
                                         Page, ParentRecord, RefreshToken, SearchHit, Store, TableRowRecord, User)


def open_store(dsn: str | None = None) -> "Store":
    """The PostgreSQL store for `dsn` (default: the DATABASE_URL environment variable)."""
    from pharmassist.store.pg import PgStore
    return PgStore.connect(dsn)
