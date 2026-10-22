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

CREATE TABLE IF NOT EXISTS llm_calls (
    id                  TEXT PRIMARY KEY,
    request_id          TEXT NOT NULL,     -- shared by a request's primary + fallback attempts
    started_at          TEXT NOT NULL,     -- ISO 8601, UTC
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    feature             TEXT NOT NULL,
    session_id          TEXT,
    attempt             INTEGER NOT NULL,
    status              TEXT NOT NULL,     -- ok | error | cancelled
    error               TEXT,
    input_tokens        INTEGER NOT NULL,  -- uncached input
    output_tokens       INTEGER NOT NULL,
    cache_read_tokens   INTEGER NOT NULL,
    cache_write_tokens  INTEGER NOT NULL,
    estimated           INTEGER NOT NULL,  -- 1 when a token count was estimated from text length
    cost_usd            REAL,              -- NULL when the model has no known price
    latency_ms          REAL NOT NULL,
    ttft_ms             REAL
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_started_at ON llm_calls (started_at);
CREATE INDEX IF NOT EXISTS idx_llm_calls_session ON llm_calls (session_id);
"""

LLM_CALL_COLUMNS = [
    "id", "request_id", "started_at", "provider", "model", "feature", "session_id",
    "attempt", "status", "error", "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_write_tokens", "estimated", "cost_usd", "latency_ms", "ttft_ms",
]

# group_by values accepted by summarize_llm_calls -> SQL expression
USAGE_GROUPS = {
    "provider": "provider",
    "model": "provider || '/' || model",
    "feature": "feature",
    "session": "session_id",
    "status": "status",
    "day": "substr(started_at, 1, 10)",
}

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


def insert_llm_call(call: dict) -> None:
    placeholders = ", ".join("?" for _ in LLM_CALL_COLUMNS)
    with _connect() as conn:
        conn.execute(
            f"INSERT INTO llm_calls ({', '.join(LLM_CALL_COLUMNS)}) VALUES ({placeholders})",
            tuple(call[c] for c in LLM_CALL_COLUMNS),
        )


def _usage_filters(since: str | None, session_id: str | None, provider: str | None) -> tuple[str, list]:
    clauses, params = [], []
    if since:
        clauses.append("started_at >= ?")
        params.append(since)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if provider:
        clauses.append("provider = ?")
        params.append(provider)
    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), params


def list_llm_calls(
    limit: int = 100, since: str | None = None, session_id: str | None = None, provider: str | None = None
) -> list[dict]:
    where, params = _usage_filters(since, session_id, provider)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM llm_calls {where} ORDER BY started_at DESC LIMIT ?", (*params, limit)
        ).fetchall()
    return [dict(row) for row in rows]


def summarize_llm_calls(
    group_by: str | None = None, since: str | None = None, session_id: str | None = None, provider: str | None = None
) -> dict:
    """Aggregate tokens, cost and latency, overall and optionally per USAGE_GROUPS key."""
    where, params = _usage_filters(since, session_id, provider)
    aggregates = """
        COUNT(*) AS calls,
        COALESCE(SUM(status = 'error'), 0) AS errors,
        COALESCE(SUM(input_tokens), 0) AS input_tokens,
        COALESCE(SUM(output_tokens), 0) AS output_tokens,
        COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
        COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
        COALESCE(SUM(cost_usd), 0) AS cost_usd,
        COALESCE(SUM(cost_usd IS NULL), 0) AS unpriced_calls,
        COALESCE(SUM(estimated), 0) AS estimated_calls,
        AVG(latency_ms) AS avg_latency_ms,
        AVG(ttft_ms) AS avg_ttft_ms
    """
    with _connect() as conn:
        total = dict(conn.execute(f"SELECT {aggregates} FROM llm_calls {where}", params).fetchone())
        groups = []
        if group_by:
            expr = USAGE_GROUPS[group_by]
            rows = conn.execute(
                f"SELECT {expr} AS key, {aggregates} FROM llm_calls {where} GROUP BY key ORDER BY cost_usd DESC, calls DESC",
                params,
            ).fetchall()
            groups = [dict(row) for row in rows]
    return {"total": total, "groups": groups}
