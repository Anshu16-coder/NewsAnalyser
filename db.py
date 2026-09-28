"""Postgres connection helper (Neon).

Uses DATABASE_URL (or POSTGRES_URL) from env. psycopg2 for local / GitHub Actions.
On Vercel the same URL is injected as an env var.
"""

import os
from urllib.parse import urlparse, unquote

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

import psycopg2
from psycopg2.extras import DictCursor


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def get_connection():
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        raise RuntimeError("Missing DATABASE_URL (or POSTGRES_URL) for Neon Postgres.")

    parsed = urlparse(url)
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        database=(parsed.path or "/").lstrip("/"),
        sslmode="require",
        cursor_factory=DictCursor,
        connect_timeout=10,
    )
    conn.autocommit = False
    return conn


def ensure_schema(connection) -> None:
    with connection.cursor() as cursor:
        with open(_schema_path(), "r", encoding="utf-8") as handle:
            cursor.execute(handle.read())
    connection.commit()


def _schema_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
