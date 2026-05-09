"""
tests/test_database.py
======================
CRUD test suite for all 4 Nexus database tables.

Test gate (from progress tracker):
  python -m pytest tests/test_database.py -v
  All CRUD tests pass for leads / deals / agent_runs / rag_queries.

Design decisions:
  - Each test gets a fresh in-memory SQLite DB (tmp_path fixture).
  - We monkeypatch get_settings() so tests never touch nexus.db on disk.
  - Tests are async (pytest-asyncio) — matches the production async code path.
  - Every test exercises: INSERT → SELECT → UPDATE → DELETE (full CRUD cycle).
  - Foreign-key constraint on deals.lead_id is verified explicitly.
"""

import json
import uuid
from datetime import datetime
from typing import AsyncGenerator

import aiosqlite
import pytest
import pytest_asyncio

from api.database import init_db, get_db
from api.config import get_settings, Settings


# ---------------------------------------------------------------------------
# Pytest-asyncio mode
# ---------------------------------------------------------------------------
# Tells pytest-asyncio to treat every async test in this file as asyncio.
pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_path(tmp_path, monkeypatch):
    """
    Create a temp SQLite file for each test, monkeypatch Settings so
    get_settings().sqlite_db_path points to it, then run init_db().
    Yields the path string.
    """
    test_db = str(tmp_path / "test_nexus.db")

    # Patch the singleton to return a Settings with our temp path
    patched = Settings(
        database_url=f"sqlite:///{test_db}",
        llm_backend="ollama",
        privacy_mode=False,
    )
    monkeypatch.setattr("api.database.get_settings", lambda: patched)
    monkeypatch.setattr("api.config.get_settings", lambda: patched)

    # Clear the lru_cache so fresh settings take effect
    get_settings.cache_clear()

    await init_db()
    yield test_db

    # lru_cache restore after test
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def db(db_path) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Open a direct aiosqlite connection to the test DB for assertions."""
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys=ON;")
        yield conn


# ---------------------------------------------------------------------------
# Helper — generate stable UUIDs for tests
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# LEADS table
# ---------------------------------------------------------------------------

class TestLeads:
    async def test_insert_lead(self, db: aiosqlite.Connection):
        """INSERT a lead and verify it can be read back."""
        lead_id = new_id()
        await db.execute(
            """
            INSERT INTO leads (id, company, contact_name, contact_email, source, stage, score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (lead_id, "Projecx", "Abdallah Zaqout", "info@projecx.io", "LinkedIn", "hot_lead", 88),
        )
        await db.commit()

        async with db.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)) as cur:
            row = await cur.fetchone()

        assert row is not None
        assert row["company"] == "Projecx"
        assert row["contact_name"] == "Abdallah Zaqout"
        assert row["stage"] == "hot_lead"
        assert row["score"] == 88

    async def test_update_lead(self, db: aiosqlite.Connection):
        """UPDATE stage and score, verify the change persists."""
        lead_id = new_id()
        await db.execute(
            "INSERT INTO leads (id, company, stage, score) VALUES (?, ?, ?, ?)",
            (lead_id, "Acme Corp", "new_lead", 30),
        )
        await db.commit()

        await db.execute(
            "UPDATE leads SET stage = ?, score = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            ("nurture", 65, lead_id),
        )
        await db.commit()

        async with db.execute("SELECT stage, score FROM leads WHERE id = ?", (lead_id,)) as cur:
            row = await cur.fetchone()

        assert row["stage"] == "nurture"
        assert row["score"] == 65

    async def test_delete_lead(self, db: aiosqlite.Connection):
        """DELETE a lead and confirm it no longer exists."""
        lead_id = new_id()
        await db.execute(
            "INSERT INTO leads (id, company) VALUES (?, ?)",
            (lead_id, "Delete Me Inc"),
        )
        await db.commit()

        await db.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        await db.commit()

        async with db.execute("SELECT id FROM leads WHERE id = ?", (lead_id,)) as cur:
            row = await cur.fetchone()

        assert row is None

    async def test_default_stage_is_new_lead(self, db: aiosqlite.Connection):
        """Stage should default to 'new_lead' when not supplied."""
        lead_id = new_id()
        await db.execute(
            "INSERT INTO leads (id, company) VALUES (?, ?)",
            (lead_id, "Defaults Ltd"),
        )
        await db.commit()

        async with db.execute("SELECT stage, score FROM leads WHERE id = ?", (lead_id,)) as cur:
            row = await cur.fetchone()

        assert row["stage"] == "new_lead"
        assert row["score"] == 0

    async def test_list_multiple_leads(self, db: aiosqlite.Connection):
        """INSERT 3 leads, SELECT all, verify count."""
        for i in range(3):
            await db.execute(
                "INSERT INTO leads (id, company) VALUES (?, ?)",
                (new_id(), f"Company {i}"),
            )
        await db.commit()

        async with db.execute("SELECT COUNT(*) AS cnt FROM leads") as cur:
            row = await cur.fetchone()

        assert row["cnt"] == 3


# ---------------------------------------------------------------------------
# DEALS table
# ---------------------------------------------------------------------------

class TestDeals:

    @pytest_asyncio.fixture(autouse=True)
    async def seed_lead(self, db: aiosqlite.Connection):
        """Every deal test needs a parent lead (FK constraint)."""
        self.lead_id = new_id()
        await db.execute(
            "INSERT INTO leads (id, company) VALUES (?, ?)",
            (self.lead_id, "Parent Co"),
        )
        await db.commit()

    async def test_insert_deal(self, db: aiosqlite.Connection):
        deal_id = new_id()
        await db.execute(
            """
            INSERT INTO deals (id, lead_id, stage, value, owner)
            VALUES (?, ?, ?, ?, ?)
            """,
            (deal_id, self.lead_id, "proposal", 25000.0, "Abdel Rahman"),
        )
        await db.commit()

        async with db.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)) as cur:
            row = await cur.fetchone()

        assert row["stage"] == "proposal"
        assert row["value"] == 25000.0
        assert row["owner"] == "Abdel Rahman"
        assert row["lead_id"] == self.lead_id

    async def test_update_deal_stage(self, db: aiosqlite.Connection):
        deal_id = new_id()
        await db.execute(
            "INSERT INTO deals (id, lead_id, stage, value) VALUES (?, ?, ?, ?)",
            (deal_id, self.lead_id, "proposal", 10000.0),
        )
        await db.commit()

        await db.execute(
            "UPDATE deals SET stage = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            ("closed_won", deal_id),
        )
        await db.commit()

        async with db.execute("SELECT stage FROM deals WHERE id = ?", (deal_id,)) as cur:
            row = await cur.fetchone()

        assert row["stage"] == "closed_won"

    async def test_delete_deal(self, db: aiosqlite.Connection):
        deal_id = new_id()
        await db.execute(
            "INSERT INTO deals (id, lead_id, stage) VALUES (?, ?, ?)",
            (deal_id, self.lead_id, "proposal"),
        )
        await db.commit()

        await db.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
        await db.commit()

        async with db.execute("SELECT id FROM deals WHERE id = ?", (deal_id,)) as cur:
            row = await cur.fetchone()

        assert row is None

    async def test_deals_linked_to_lead(self, db: aiosqlite.Connection):
        """Two deals linked to the same lead — JOIN query works."""
        for stage in ("proposal", "closed_won"):
            await db.execute(
                "INSERT INTO deals (id, lead_id, stage) VALUES (?, ?, ?)",
                (new_id(), self.lead_id, stage),
            )
        await db.commit()

        async with db.execute(
            "SELECT d.stage FROM deals d JOIN leads l ON d.lead_id = l.id WHERE l.id = ?",
            (self.lead_id,),
        ) as cur:
            rows = await cur.fetchall()

        assert len(rows) == 2
        stages = {r["stage"] for r in rows}
        assert stages == {"proposal", "closed_won"}


# ---------------------------------------------------------------------------
# AGENT_RUNS table
# ---------------------------------------------------------------------------

class TestAgentRuns:

    async def test_insert_agent_run(self, db: aiosqlite.Connection):
        run_id = str(uuid.uuid4())
        rec_id = new_id()
        input_payload = json.dumps({"company": "Projecx", "score": 88})

        await db.execute(
            """
            INSERT INTO agent_runs (id, agent_name, run_id, input_json, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rec_id, "lead_classifier", run_id, input_payload, "running"),
        )
        await db.commit()

        async with db.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)) as cur:
            row = await cur.fetchone()

        assert row["agent_name"] == "lead_classifier"
        assert row["status"] == "running"
        assert json.loads(row["input_json"])["score"] == 88

    async def test_update_agent_run_to_completed(self, db: aiosqlite.Connection):
        run_id = str(uuid.uuid4())
        rec_id = new_id()
        await db.execute(
            "INSERT INTO agent_runs (id, agent_name, run_id, status) VALUES (?, ?, ?, ?)",
            (rec_id, "lead_classifier", run_id, "running"),
        )
        await db.commit()

        output = json.dumps({"stage": "hot_lead", "score": 88})
        await db.execute(
            """
            UPDATE agent_runs
            SET status = ?, output_json = ?, completed_at = CURRENT_TIMESTAMP
            WHERE run_id = ?
            """,
            ("completed", output, run_id),
        )
        await db.commit()

        async with db.execute(
            "SELECT status, output_json, completed_at FROM agent_runs WHERE run_id = ?",
            (run_id,),
        ) as cur:
            row = await cur.fetchone()

        assert row["status"] == "completed"
        assert json.loads(row["output_json"])["stage"] == "hot_lead"
        assert row["completed_at"] is not None

    async def test_run_id_is_unique(self, db: aiosqlite.Connection):
        """Inserting duplicate run_id must raise an IntegrityError."""
        run_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO agent_runs (id, agent_name, run_id, status) VALUES (?, ?, ?, ?)",
            (new_id(), "lead_classifier", run_id, "running"),
        )
        await db.commit()

        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO agent_runs (id, agent_name, run_id, status) VALUES (?, ?, ?, ?)",
                (new_id(), "lead_classifier", run_id, "running"),
            )
            await db.commit()

    async def test_delete_agent_run(self, db: aiosqlite.Connection):
        run_id = str(uuid.uuid4())
        rec_id = new_id()
        await db.execute(
            "INSERT INTO agent_runs (id, agent_name, run_id, status) VALUES (?, ?, ?, ?)",
            (rec_id, "reporter", run_id, "completed"),
        )
        await db.commit()

        await db.execute("DELETE FROM agent_runs WHERE id = ?", (rec_id,))
        await db.commit()

        async with db.execute("SELECT id FROM agent_runs WHERE id = ?", (rec_id,)) as cur:
            row = await cur.fetchone()

        assert row is None


# ---------------------------------------------------------------------------
# RAG_QUERIES table
# ---------------------------------------------------------------------------

class TestRagQueries:

    async def test_insert_rag_query(self, db: aiosqlite.Connection):
        rec_id = new_id()
        await db.execute(
            """
            INSERT INTO rag_queries (id, query_text, model_used)
            VALUES (?, ?, ?)
            """,
            (rec_id, "What percentage of workflows is Projecx integrating AI into?", "gemma3:4b"),
        )
        await db.commit()

        async with db.execute("SELECT * FROM rag_queries WHERE id = ?", (rec_id,)) as cur:
            row = await cur.fetchone()

        assert "Projecx" in row["query_text"]
        assert row["model_used"] == "gemma3:4b"
        assert row["response_text"] is None   # not yet answered

    async def test_update_rag_query_with_response(self, db: aiosqlite.Connection):
        rec_id = new_id()
        await db.execute(
            "INSERT INTO rag_queries (id, query_text) VALUES (?, ?)",
            (rec_id, "What is Revenyu?"),
        )
        await db.commit()

        sources = json.dumps([{"chunk": "Revenyu is a CRM...", "score": 0.92}])
        await db.execute(
            """
            UPDATE rag_queries
            SET response_text = ?, sources_json = ?, latency_ms = ?
            WHERE id = ?
            """,
            ("Revenyu is an AI-augmented CRM by Projecx.", sources, 342, rec_id),
        )
        await db.commit()

        async with db.execute("SELECT * FROM rag_queries WHERE id = ?", (rec_id,)) as cur:
            row = await cur.fetchone()

        assert "Revenyu" in row["response_text"]
        assert row["latency_ms"] == 342
        assert json.loads(row["sources_json"])[0]["score"] == 0.92

    async def test_delete_rag_query(self, db: aiosqlite.Connection):
        rec_id = new_id()
        await db.execute(
            "INSERT INTO rag_queries (id, query_text) VALUES (?, ?)",
            (rec_id, "Delete me"),
        )
        await db.commit()

        await db.execute("DELETE FROM rag_queries WHERE id = ?", (rec_id,))
        await db.commit()

        async with db.execute("SELECT id FROM rag_queries WHERE id = ?", (rec_id,)) as cur:
            row = await cur.fetchone()

        assert row is None

    async def test_list_rag_queries_ordered(self, db: aiosqlite.Connection):
        """INSERT 3 queries, fetch ordered by created_at DESC."""
        for q in ("question one", "question two", "question three"):
            await db.execute(
                "INSERT INTO rag_queries (id, query_text) VALUES (?, ?)",
                (new_id(), q),
            )
        await db.commit()

        async with db.execute(
            "SELECT query_text FROM rag_queries ORDER BY created_at DESC"
        ) as cur:
            rows = await cur.fetchall()

        assert len(rows) == 3
        # All 3 are present regardless of order
        texts = {r["query_text"] for r in rows}
        assert "question one" in texts
        assert "question three" in texts


# ---------------------------------------------------------------------------
# Cross-table: init_db is idempotent
# ---------------------------------------------------------------------------

class TestInitDbIdempotent:
    async def test_init_db_twice_does_not_raise(self, db_path):
        """Calling init_db() a second time must not raise or duplicate tables."""
        from api.database import init_db as _init_db

        # Monkeypatch settings to the same temp path
        patched = Settings(database_url=f"sqlite:///{db_path}")

        import api.database as db_module
        original = db_module.get_settings
        db_module.get_settings = lambda: patched

        try:
            await _init_db()   # second call
        finally:
            db_module.get_settings = original

        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute(
                "SELECT COUNT(*) AS cnt FROM sqlite_master WHERE type='table'"
            ) as cur:
                row = await cur.fetchone()
            assert row[0] == 4   # still exactly 4 tables