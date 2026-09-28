"""MySQL connection helper.

Every database detail comes from environment variables so the same code runs
locally, in GitHub Actions, and on Vercel without edits:

    DB_HOST     MySQL hostname (e.g. your-db-host.railway.app)
    DB_PORT     MySQL port, defaults to 3306
    DB_USER     MySQL user
    DB_PASSWORD MySQL password
    DB_NAME     MySQL database name
    DB_SSL      set to "1"/"true" to require TLS (hosted providers usually need this)

DB_URL (sqlalchemy-style, e.g. mysql+pymysql://user:pw@host:3306/db) is also
accepted and takes precedence, for users who prefer a single variable.

Local development puts these in a `.env` file next to db.py (see .env.example).
Real environment variables always win, so production config is never shadowed.
"""

import os
from urllib.parse import urlparse, unquote

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    # python-dotenv is only needed for local development. On Vercel and in
    # GitHub Actions the variables are already in the real environment.
    pass

import pymysql
from pymysql.cursors import DictCursor


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _settings_from_url(url: str) -> dict:
    parsed = urlparse(url.replace("mysql+pymysql://", "mysql://", 1))
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": (parsed.path or "/").lstrip("/"),
    }


def get_connection():
    """Return a fresh pymysql connection, or raise a readable error."""
    url = os.environ.get("DB_URL", "").strip()
    settings = _settings_from_url(url) if url else {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "3306") or 3306),
        "user": os.environ.get("DB_USER", ""),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", ""),
    }

    missing = [key for key, value in settings.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing MySQL configuration: "
            + ", ".join(missing)
            + ". Set DB_HOST, DB_USER, DB_PASSWORD and DB_NAME (or DB_URL)."
        )

    return pymysql.connect(
        host=settings["host"],
        port=settings["port"],
        user=settings["user"],
        password=settings["password"],
        database=settings["database"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        ssl={"ssl": {}} if _env_flag("DB_SSL") else None,
        connect_timeout=10,
    )


def ensure_schema(connection) -> None:
    """Create the articles table if it does not already exist."""
    with connection.cursor() as cursor:
        with open(_schema_path(), "r", encoding="utf-8") as handle:
            cursor.execute(handle.read())
    connection.commit()


def _schema_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
