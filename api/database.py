"""
api/database.py
===============
SQLite singleton for Nexus-AI.

Rules enforced here:
  - SQLite only, WAL mode (set on every connection).
  - Async via aiosqlite — all I/O is non-blocking.
  - Single init_db() call creates all 4 tables if they don't exist.
  - get_db() is an async context manager for request-scoped connections.
  - Zero hardcoded paths — db path comes from config.get_settings().

Tables: leads · deals · agent_runs · rag_queries
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiosqlite

from api.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL — 4 tables, exact schema from 5_NEXUS_PROJECT_SKILL.md
# ---------------------------------------------------------------------------

_DDL_LEADS = """
CREATE TABLE IF NOT EXISTS leads (
    id            TEXT PRIMARY KEY,
    company       TEXT NOT NULL,
    contact_name  TEXT,
    contact_email TEXT,
    source        TEXT,
    stage         TEXT DEFAULT 'new_lead',
    score         INTEGER DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_DDL_DEALS = """
CREATE TABLE IF NOT EXISTS deals (
    id            TEXT PRIMARY KEY,
    lead_id       TEXT REFERENCES leads(id),
    stage         TEXT NOT NULL,
    value         REAL,
    owner         TEXT,
    last_contact  TIMESTAMP,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_DDL_AGENT_RUNS = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id           TEXT PRIMARY KEY,
    agent_name   TEXT NOT NULL,
    run_id       TEXT UNIQUE NOT NULL,
    input_json   TEXT,
    output_json  TEXT,
    status       TEXT DEFAULT 'running',
    started_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);
"""

_DDL_RAG_QUERIES = """
CREATE TABLE IF NOT EXISTS rag_queries (
    id            TEXT PRIMARY KEY,
    query_text    TEXT NOT NULL,
    response_text TEXT,
    sources_json  TEXT,
    latency_ms    INTEGER,
    model_used    TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_ALL_DDL = [_DDL_LEADS, _DDL_DEALS, _DDL_AGENT_RUNS, _DDL_RAG_QUERIES]

# ---------------------------------------------------------------------------
# WAL pragma helper
# ---------------------------------------------------------------------------

async def _enable_wal(conn: aiosqlite.Connection) -> None:
    """Enable WAL mode and foreign-key enforcement on a connection."""
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA foreign_keys=ON;")
    await conn.commit()


# ---------------------------------------------------------------------------
# init_db — called once at application startup
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """
    Create all 4 tables if they don't already exist.
    Safe to call on every startup (all statements use IF NOT EXISTS).
    """
    settings = get_settings()
    db_path = settings.sqlite_db_path

    logger.info("Initialising database at %s", db_path)

    async with aiosqlite.connect(db_path) as conn:
        await _enable_wal(conn)
        for ddl in _ALL_DDL:
            await conn.execute(ddl)
        await conn.commit()

    logger.info("Database ready — 4 tables confirmed.")


# ---------------------------------------------------------------------------
# get_db — async context manager for a single request-scoped connection
# ---------------------------------------------------------------------------

@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """
    Yield an open, WAL-enabled aiosqlite connection.

    Usage:
        async with get_db() as db:
            await db.execute("SELECT * FROM leads")
            await db.commit()

    The connection is always closed when the block exits, even on error.
    """
    settings = get_settings()
    db_path = settings.sqlite_db_path

    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row   # rows accessible as dicts / by name
        await _enable_wal(conn)
        try:
            yield conn
        except Exception:
            await conn.rollback()
            raise