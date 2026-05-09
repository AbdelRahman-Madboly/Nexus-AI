"""
tests/test_agents.py
====================
Pytest suite for Phase 2 LangGraph agents.

Day 7: TestFollowupWriter — seeds its own lead + deal into an isolated temp DB,
       runs write_followup(), and asserts the draft and review_score are valid.

Each test class gets its own isolated SQLite DB via tmp_path + monkeypatch,
exactly like test_database.py. Never touches the real nexus.db.

Run:
    python -m pytest tests/test_agents.py -v
"""

import asyncio
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from api.database import init_db, get_db


# ---------------------------------------------------------------------------
# Shared fixture: isolated temp DB (same pattern as test_database.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """
    Override get_settings() so all DB calls use a fresh temp SQLite file.
    Isolated per test — never touches nexus.db.
    """
    db_file = tmp_path / "test_nexus.db"

    from api import config as config_module
    from unittest.mock import MagicMock

    mock_settings = MagicMock()
    mock_settings.sqlite_db_path = str(db_file)
    mock_settings.effective_llm_backend = "ollama"
    mock_settings.privacy_mode = False

    monkeypatch.setattr(config_module, "get_settings", lambda: mock_settings)

    # Also patch inside database module (it imports get_settings at call time)
    import api.database as db_module
    monkeypatch.setattr(db_module, "get_settings", lambda: mock_settings)

    return str(db_file)


async def _seed_deal(db_path: str) -> tuple[str, str]:
    """
    Insert a test lead and deal into the temp DB.
    Returns (lead_id, deal_id).
    """
    lead_id = str(uuid4())
    deal_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    from api.database import get_db
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO leads (id, company, contact_name, contact_email, source, stage, score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (lead_id, "Gulf Properties LLC", "Ahmed Al-Mansouri",
             "ahmed@gulf-properties.ae", "Website", "nurture", 75),
        )
        await db.execute(
            """
            INSERT INTO deals (id, lead_id, stage, value, owner, last_contact)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (deal_id, lead_id, "nurture", 50000.0, "Sales Team", now),
        )
        await db.commit()

    return lead_id, deal_id


# ---------------------------------------------------------------------------
# TestFollowupWriter
# ---------------------------------------------------------------------------

class TestFollowupWriter:
    """
    Tests for the Follow-up Writer Agent (followup_agent.py).

    Uses a temp DB with a seeded deal. Mocks the LLM (llm_router.complete)
    and the RAG retriever so the test never hits real Ollama/Gemini/ChromaDB.
    This keeps the test fast, deterministic, and free of external dependencies.
    """

    @pytest.mark.asyncio
    async def test_write_followup_returns_valid_draft(self, temp_db):
        """
        Happy path: seeded deal → write_followup() → draft non-empty, score valid.
        """
        # Init the temp DB tables
        await init_db()

        # Seed the test deal
        lead_id, deal_id = await _seed_deal(temp_db)

        # Mock LLM calls so we don't need Ollama/Gemini running
        # draft_email returns a plausible email; self_review returns SCORE: 85
        call_count = {"n": 0}

        async def mock_complete(prompt, system="", model=None):
            call_count["n"] += 1
            # self_review call is detected by the SCORE/NOTES format request in prompt
            if "SCORE:" in prompt or "Scoring criteria" in prompt:
                return "SCORE: 85\nNOTES: None"
            # draft_email call
            return (
                f"Hi Ahmed,\n\n"
                f"I wanted to follow up on Gulf Properties LLC's interest in our CRM solution. "
                f"Given your 200-agent deployment goal, I believe we can help you streamline "
                f"lead management across all three cities.\n\n"
                f"Would you be available for a 30-minute call this week to walk through a "
                f"tailored demo?\n\n"
                f"Best regards,\nNexus Team"
            )

        # Mock RAG retriever so ChromaDB isn't needed
        async def mock_rag_query(q, top_k=3, stream=False):
            from api.rag.retriever import QueryResult
            return QueryResult(
                answer="Nexus CRM supports multi-city deployments.",
                sources=[{"id": "c1", "text": "Nexus CRM supports large teams.", "metadata": {}, "score": 0.9}],
                latency_ms=10,
            )

        with patch("api.agents.followup_agent.complete", side_effect=mock_complete), \
             patch("api.agents.followup_agent.rag_query", side_effect=mock_rag_query), \
             patch("api.agents.graph.get_db", get_db), \
             patch("api.agents.followup_agent.get_db", get_db):

            from api.agents.followup_agent import write_followup
            result = await write_followup(deal_id=deal_id)

        # Assertions
        assert isinstance(result["draft"], str), "draft must be a string"
        assert len(result["draft"]) > 20,        "draft must be non-empty"
        assert "Ahmed" in result["draft"],        "draft must address contact by name"
        assert isinstance(result["review_score"], int), "review_score must be int"
        assert 0 <= result["review_score"] <= 100,      "review_score must be 0-100"
        assert result["review_score"] > 0,              "review_score must be > 0"
        assert isinstance(result["run_id"], str),        "run_id must be a string"
        assert len(result["run_id"]) > 0,                "run_id must be non-empty"

    @pytest.mark.asyncio
    async def test_write_followup_deal_not_found(self, temp_db):
        """
        If deal_id doesn't exist, write_followup raises ValueError.
        """
        await init_db()

        fake_deal_id = str(uuid4())

        with patch("api.agents.graph.get_db", get_db), \
             patch("api.agents.followup_agent.get_db", get_db):

            from api.agents.followup_agent import write_followup
            with pytest.raises(ValueError, match="not found"):
                await write_followup(deal_id=fake_deal_id)

    @pytest.mark.asyncio
    async def test_write_followup_self_review_loop(self, temp_db):
        """
        When first draft scores < 70, the agent loops back to draft_email.
        Verify it still returns a valid result (best effort after retries).
        """
        await init_db()
        lead_id, deal_id = await _seed_deal(temp_db)

        draft_call_count = {"n": 0}

        async def mock_complete_low_score(prompt, system="", model=None):
            if "SCORE:" in prompt or "Scoring criteria" in prompt:
                # Always score below threshold — forces max retries
                return "SCORE: 55\nNOTES: Missing a clear call to action."
            draft_call_count["n"] += 1
            return f"Hi Ahmed, following up. Draft attempt {draft_call_count['n']}."

        async def mock_rag_query(q, top_k=3, stream=False):
            from api.rag.retriever import QueryResult
            return QueryResult(answer="", sources=[], latency_ms=5)

        with patch("api.agents.followup_agent.complete", side_effect=mock_complete_low_score), \
             patch("api.agents.followup_agent.rag_query", side_effect=mock_rag_query), \
             patch("api.agents.graph.get_db", get_db), \
             patch("api.agents.followup_agent.get_db", get_db):

            from api.agents.followup_agent import write_followup
            result = await write_followup(deal_id=deal_id)

        # Even with low score, must return a result (not raise) after max retries
        assert isinstance(result["draft"], str)
        assert len(result["draft"]) > 0
        # draft_email should have been called exactly 2 times:
        # attempt 1 (retry_count goes 0→1), attempt 2 (retry_count goes 1→2).
        # On attempt 2, route_by_confidence sees retry_count=2 (not < 2) → END.
        assert draft_call_count["n"] == 2, (
            f"Expected 2 draft attempts (1 original + 1 retry), got {draft_call_count['n']}"
        )

    @pytest.mark.asyncio
    async def test_agent_run_logged_to_db(self, temp_db):
        """
        After write_followup(), a row must exist in agent_runs with status='completed'.
        """
        await init_db()
        lead_id, deal_id = await _seed_deal(temp_db)

        async def mock_complete(prompt, system="", model=None):
            if "SCORE:" in prompt or "Scoring criteria" in prompt:
                return "SCORE: 80\nNOTES: None"
            return "Hi Ahmed, let's reconnect about Gulf Properties LLC. Can we meet Thursday?"

        async def mock_rag_query(q, top_k=3, stream=False):
            from api.rag.retriever import QueryResult
            return QueryResult(answer="", sources=[], latency_ms=5)

        with patch("api.agents.followup_agent.complete", side_effect=mock_complete), \
             patch("api.agents.followup_agent.rag_query", side_effect=mock_rag_query), \
             patch("api.agents.graph.get_db", get_db), \
             patch("api.agents.followup_agent.get_db", get_db):

            from api.agents.followup_agent import write_followup
            result = await write_followup(deal_id=deal_id)

        # Check the agent_runs row was written
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT status, agent_name FROM agent_runs WHERE run_id = ?",
                (result["run_id"],),
            )
            row = await cursor.fetchone()

        assert row is not None,                   "agent_runs row must exist"
        assert row["status"] == "completed",       "status must be 'completed'"
        assert row["agent_name"] == "followup_writer", "agent_name must be 'followup_writer'"