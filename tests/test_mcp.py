"""
tests/test_mcp.py
=================
Unit tests for the Nexus-AI MCP server tools.

Coverage:
  test_nexus_query_leads_all             — returns all leads from an isolated DB
  test_nexus_query_leads_filtered_by_stage — stage filter returns only matching leads
  test_nexus_query_deals_with_join       — deal rows include company field from JOIN
  test_nexus_get_deal_history_found      — returns deal + lead dict for a valid deal_id
  test_nexus_get_deal_history_not_found  — returns {error} for unknown deal_id
  test_nexus_update_deal_stage           — updates deal stage and confirms in DB

Scope:
  - Tests use an isolated temp SQLite DB (tmp_path fixture)
  - get_db() inside each MCP tool is patched to use the temp DB
  - nexus_pipeline_kpis and nexus_schedule_followup invoke full LangGraph agents
    and are NOT unit-tested here — smoke-test them via curl after the server starts.

Patch target note (CRITICAL):
  Always patch 'api.mcp.server.get_db' (where get_db is *used*),
  NOT 'api.database.get_db' (where it is *defined*).
  Patching the definition site has no effect on already-imported references.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

import aiosqlite
import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Fixtures — isolated temp SQLite DB for each test
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db_path(tmp_path):
    """Return a path string for a fresh temp SQLite file."""
    return str(tmp_path / "test_mcp.db")


@pytest_asyncio.fixture
async def initialized_db(temp_db_path):
    """
    Create and initialise the 4-table schema in a temp DB.
    Yields the db path string — tests use it to wire get_db() mock.
    """
    mock_settings = MagicMock()
    mock_settings.sqlite_db_path = temp_db_path
    mock_settings.effective_llm_backend = "gemini"
    mock_settings.privacy_mode = False

    with patch("api.database.get_settings", return_value=mock_settings):
        from api.database import init_db
        await init_db()

    yield temp_db_path


def make_get_db(db_path: str):
    """
    Return a get_db() replacement that opens the given temp DB path.
    This is the correct pattern for patching MCP tool DB access.
    """
    @asynccontextmanager
    async def _get_db():
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            try:
                yield conn
            except Exception:
                await conn.rollback()
                raise

    return _get_db


# ---------------------------------------------------------------------------
# Helpers — seed data into the isolated DB
# ---------------------------------------------------------------------------

async def _insert_lead(db_path: str, stage: str = "new_lead", company: str = "Test Corp") -> str:
    """Insert a single lead and return its id."""
    lead_id = str(uuid4())
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            INSERT INTO leads (id, company, contact_name, contact_email, source, stage, score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (lead_id, company, "Test User", "test@example.com", "website", stage, 75),
        )
        await conn.commit()
    return lead_id


async def _insert_deal(db_path: str, lead_id: str, stage: str = "proposal") -> str:
    """Insert a single deal for a given lead and return its id."""
    deal_id = str(uuid4())
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            INSERT INTO deals (id, lead_id, stage, value, owner)
            VALUES (?, ?, ?, ?, ?)
            """,
            (deal_id, lead_id, stage, 5000.0, "Alice"),
        )
        await conn.commit()
    return deal_id


# ---------------------------------------------------------------------------
# Test 1: nexus_query_leads_all — returns all leads
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nexus_query_leads_all(initialized_db):
    """Insert 3 leads in different stages; query_leads() with no filter returns all 3."""
    db_path = initialized_db

    await _insert_lead(db_path, stage="new_lead",  company="Alpha Inc")
    await _insert_lead(db_path, stage="hot_lead",  company="Beta Ltd")
    await _insert_lead(db_path, stage="nurture",   company="Gamma Co")

    with patch("api.mcp.server.get_db", make_get_db(db_path)):
        from api.mcp.server import nexus_query_leads
        results = await nexus_query_leads()

    assert len(results) == 3
    required_keys = {"id", "company", "contact_name", "stage", "score"}
    for row in results:
        assert required_keys.issubset(row.keys()), f"Missing keys in lead row: {row.keys()}"


# ---------------------------------------------------------------------------
# Test 2: nexus_query_leads_filtered_by_stage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nexus_query_leads_filtered_by_stage(initialized_db):
    """Insert 2 hot_leads + 1 nurture; filtering for hot_lead returns exactly 2."""
    db_path = initialized_db

    await _insert_lead(db_path, stage="hot_lead", company="HotCo 1")
    await _insert_lead(db_path, stage="hot_lead", company="HotCo 2")
    await _insert_lead(db_path, stage="nurture",  company="NurtureCo")

    with patch("api.mcp.server.get_db", make_get_db(db_path)):
        from api.mcp.server import nexus_query_leads
        results = await nexus_query_leads(stage="hot_lead")

    assert len(results) == 2
    for row in results:
        assert row["stage"] == "hot_lead", f"Unexpected stage: {row['stage']}"


# ---------------------------------------------------------------------------
# Test 3: nexus_query_deals_with_join — company field comes from leads JOIN
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nexus_query_deals_with_join(initialized_db):
    """Insert 1 lead + 2 deals; each deal row should include the company from leads."""
    db_path = initialized_db

    lead_id = await _insert_lead(db_path, company="Joined Corp")
    await _insert_deal(db_path, lead_id, stage="proposal")
    await _insert_deal(db_path, lead_id, stage="hot_lead")

    with patch("api.mcp.server.get_db", make_get_db(db_path)):
        from api.mcp.server import nexus_query_deals
        results = await nexus_query_deals()

    assert len(results) == 2
    for row in results:
        assert "company" in row, "Deal row missing 'company' field from JOIN"
        assert row["company"] == "Joined Corp"


# ---------------------------------------------------------------------------
# Test 4: nexus_get_deal_history_found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nexus_get_deal_history_found(initialized_db):
    """Insert lead + deal; get_deal_history returns both under 'deal' and 'lead' keys."""
    db_path = initialized_db

    lead_id = await _insert_lead(db_path, company="History Corp")
    deal_id = await _insert_deal(db_path, lead_id, stage="proposal")

    with patch("api.mcp.server.get_db", make_get_db(db_path)):
        from api.mcp.server import nexus_get_deal_history
        result = await nexus_get_deal_history(deal_id=deal_id)

    assert "deal" in result, "Result missing 'deal' key"
    assert "lead" in result, "Result missing 'lead' key"
    assert result["deal"]["id"] == deal_id
    assert result["lead"]["id"] == lead_id
    assert result["lead"]["company"] == "History Corp"


# ---------------------------------------------------------------------------
# Test 5: nexus_get_deal_history_not_found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nexus_get_deal_history_not_found(initialized_db):
    """Querying a nonexistent deal_id returns {error: 'Deal not found'}."""
    db_path = initialized_db

    with patch("api.mcp.server.get_db", make_get_db(db_path)):
        from api.mcp.server import nexus_get_deal_history
        result = await nexus_get_deal_history(deal_id="nonexistent-uuid-0000")

    assert result == {"error": "Deal not found"}


# ---------------------------------------------------------------------------
# Test 6: nexus_update_deal_stage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nexus_update_deal_stage(initialized_db):
    """
    Insert lead + deal at stage='new_lead';
    call update_deal_stage to 'hot_lead';
    assert success=True then verify stage in DB is actually 'hot_lead'.
    """
    db_path = initialized_db

    lead_id = await _insert_lead(db_path, stage="new_lead", company="Update Corp")
    deal_id = await _insert_deal(db_path, lead_id, stage="new_lead")

    with patch("api.mcp.server.get_db", make_get_db(db_path)):
        from api.mcp.server import nexus_update_deal_stage
        result = await nexus_update_deal_stage(deal_id=deal_id, new_stage="hot_lead")

    assert result["success"] is True, f"Expected success=True, got: {result}"
    assert result["new_stage"] == "hot_lead"
    assert result["deal_id"] == deal_id

    # Verify the change actually landed in the DB
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("SELECT stage FROM deals WHERE id = ?", (deal_id,))
        row = await cursor.fetchone()

    assert row is not None
    assert row["stage"] == "hot_lead", f"DB still shows stage={row['stage']}"