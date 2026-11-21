"""Alembic environment: connects with the DSN PgStore.migrate() passes (config.attributes["dsn"])
or, from the CLI, the DATABASE_URL variable named by config.yaml `database.url_env`.

SQLAlchemy only drives the migration connection; the application itself talks psycopg 3 directly.
"""

import os

from alembic import context
from sqlalchemy import create_engine


def _dsn() -> str:
    dsn = context.config.attributes.get("dsn")
    if not dsn:
        var = "DATABASE_URL"
        try:
            from pharmassist.config import load_config
            var = load_config().get("database", {}).get("url_env", var)
        except Exception:
            pass
        dsn = os.environ.get(var)
    if not dsn:
        raise RuntimeError("no database DSN: set DATABASE_URL (or pass config.attributes['dsn'])")
    return sqlalchemy_url(dsn)


def sqlalchemy_url(dsn: str) -> str:
    """A libpq DSN as SQLAlchemy's psycopg-3 URL (SQLAlchemy defaults 'postgresql://' to psycopg2)."""
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg://" + dsn[len(prefix):]
    return dsn


def run_migrations_online() -> None:
    engine = create_engine(_dsn(), poolclass=None)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline (SQL-script) mode isn't supported; the baseline runs the SQL file directly")
run_migrations_online()
