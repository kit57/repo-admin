import os
import sqlite3
from datetime import datetime, timezone

from models import RepoSummary

DB_PATH = os.getenv("DB_PATH") or os.path.join(os.path.dirname(__file__), "repo_admin.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    id              INTEGER PRIMARY KEY,   -- GitHub repo id
    full_name       TEXT NOT NULL UNIQUE,
    owner           TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    html_url        TEXT NOT NULL,
    private         INTEGER NOT NULL DEFAULT 0,
    fork            INTEGER NOT NULL DEFAULT 0,
    archived        INTEGER NOT NULL DEFAULT 0,
    language        TEXT,
    stars           INTEGER NOT NULL DEFAULT 0,
    forks           INTEGER NOT NULL DEFAULT 0,
    open_issues     INTEGER NOT NULL DEFAULT 0,
    default_branch  TEXT,
    pushed_at       TEXT,
    updated_at      TEXT,
    synced_at       TEXT NOT NULL
);
"""

REPO_COLUMNS = [
    "id", "full_name", "owner", "name", "description", "html_url",
    "private", "fork", "archived", "language", "stars", "forks",
    "open_issues", "default_branch", "pushed_at", "updated_at", "synced_at",
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def replace_repos(repos: list[RepoSummary]) -> str:
    """Upsert the given repos and drop any that no longer exist on GitHub. Returns the sync timestamp."""
    synced_at = datetime.now(timezone.utc).isoformat()
    placeholders = ", ".join("?" for _ in REPO_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in REPO_COLUMNS if c != "id")

    with _connect() as conn:
        conn.executemany(
            f"INSERT INTO repos ({', '.join(REPO_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            [
                tuple(synced_at if c == "synced_at" else getattr(r, c) for c in REPO_COLUMNS)
                for r in repos
            ],
        )
        conn.execute("DELETE FROM repos WHERE synced_at != ?", (synced_at,))

    return synced_at


def list_repos() -> list[RepoSummary]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM repos ORDER BY pushed_at DESC").fetchall()
    return [RepoSummary(**dict(row)) for row in rows]


def last_synced_at() -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT MAX(synced_at) FROM repos").fetchone()
    return row[0]
