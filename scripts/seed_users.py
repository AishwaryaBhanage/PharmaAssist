"""Seed the default accounts: one admin and three staff users.

    PYTHONPATH=src .venv/bin/python scripts/seed_users.py [--password-file PATH] [--dsn DATABASE_URL]

Emails: admin@pharmassist.local, staff1..3@pharmassist.local. Passwords come from --password-file
(one `email=password` or `email password` per line; missing emails get generated ones) or are
generated (URL-safe, 16 chars) and printed ONCE to the terminal, never logged or written anywhere.
Idempotent: an account that already exists is left untouched (its password is not reset) and the
script says so. Run against docker-compose locally or through the deploy's migration task on AWS.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # so `app.*` imports work from scripts/

from app.auth import hash_password  # noqa: E402

SEED = [("admin@pharmassist.local", "admin", "Administrator"), ("staff1@pharmassist.local", "staff", "Staff One"),
        ("staff2@pharmassist.local", "staff", "Staff Two"), ("staff3@pharmassist.local", "staff", "Staff Three")]


def read_passwords(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        email, _, password = line.partition("=") if "=" in line else line.partition(" ")
        if email.strip() and password.strip():
            out[email.strip().lower()] = password.strip()
    return out


def seed(store, passwords: dict[str, str], out=print) -> list[tuple[str, str, str | None]]:
    """Returns (email, outcome, password-or-None); the password is only set for accounts created now."""
    results = []
    for email, role, name in SEED:
        if store.users.by_email_for_login(email) is not None:
            results.append((email, "exists", None))
            continue
        password = passwords.get(email) or secrets.token_urlsafe(12)
        store.users.create(email, hash_password(password), role, name)
        results.append((email, "created", password))
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--password-file", type=Path, help="email=password lines; others are generated")
    ap.add_argument("--dsn", help="PostgreSQL DSN (default: DATABASE_URL)")
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from pharmassist.store import open_store
    store = open_store(args.dsn or os.environ.get("DATABASE_URL"))
    try:
        results = seed(store, read_passwords(args.password_file))
    finally:
        store.close()
    print("Seeded users (passwords are shown once; store them in a password manager now):")
    for email, outcome, password in results:
        print(f"  {email:<32} {outcome:<8} {password or '(unchanged)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
