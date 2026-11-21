"""Baseline schema: executes db/migrations/0001_init.sql verbatim.

The SQL file stays the readable contract every stream codes against; this revision only runs it,
so the two can never drift. Later revisions are ordinary Alembic scripts.

Revision ID: 0001
Revises: None
"""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "migrations" / "0001_init.sql"
TABLES = ("usage_days", "feedback", "messages", "conversations", "index_state", "ingestion_jobs", "table_rows",
          "figures", "chunks", "parents", "document_versions", "documents", "refresh_tokens", "users")


def upgrade() -> None:
    # exec_driver_sql: the raw multi-statement script goes to psycopg untouched (no bind-param parsing)
    op.get_bind().exec_driver_sql(SQL_FILE.read_text())


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_active_version_fk")
    for t in TABLES:
        bind.exec_driver_sql(f"DROP TABLE IF EXISTS {t} CASCADE")
