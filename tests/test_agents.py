"""
tests/test_agents.py
====================
Phase 2 full test suite — 7 tests covering all three LangGraph agents.

Test classes:
  TestLeadClassifier   — 5 parametrized leads covering the full routing space
  TestFollowupWriter   — 1 test: seeds a deal, calls write_followup, asserts draft quality
  TestPipelineReporter — 1 test: calls generate_report, asserts all 4 KPI keys present

Design rules:
  - All tests are async (pytest-asyncio).
  - All tests use an isolated temp SQLite DB via tmp_path + monkeypatch.
  - LLM calls are mocked so tests run without Ollama, Gemini, or ChromaDB.
  - RAG calls are mocked to return a fixed 3-chunk response.
  - Each test is independent — no shared state between tests.

Why mock LLM and RAG?
  Unit tests should be deterministic and fast. Mocking lets us test the agent
  logic (state flow, routing rules, retry behaviour) without network calls.
  End-to-end smoke tests (curl-based) are done manually after each day.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
import aiosqlite

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """
    Create an isolated SQLite DB for each test.

    Monkeypatches get_settings() so all database calls within the test
    point to the temp file, not the real nexus.db.
    """
    db_path = str(tmp_path / "test_nexus.db")

    # Patch settings to point at the temp db
    mock_settings = MagicMock()
    mock_settings.sqlite_db_path = db_path
    mock_settings.effective_llm_backend = "ollama"
    mock_settings.privacy_mode = False

    monkeypatch.setattr("api.config.get_settings", lambda: mock_settings)
    monkeypatch.setattr("api.database.get_settings", lambda: mock_settings)
    monkeypatch.setattr("api.agents.graph.get_settings", lambda: mock_settings)

    return db_path


@pytest_asyncio.fixture
async def initialized_db(temp_db):
    """
    Run init_db() against the temp DB to create all 4 tables.
    Returns the db_path for direct aiosqlite access in tests.

    Uses @pytest_asyncio.fixture (not @pytest.fixture) because it is async.
    In pytest-asyncio strict mode, async fixtures MUST use this decorator —
    plain @pytest.fixture on an async def is an error in pytest 9.
    """
    from api.database import init_db
    await init_db()
    return temp_db


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

def make_rag_mock():
    """
    Return a mock QueryResult with 3 fixed source chunks.
    Used to prevent actual ChromaDB calls in agent tests.
    """
    mock_result = MagicMock()
    mock_result.sources = [
        {"text": "Revenyu is a next-gen CRM with AI agent layer built on Llama 3."},
        {"text": "Projecx integrates AI into 70% of workflows for business automation."},
        {"text": "Bandora is Projecx's AI content intelligence platform."},
    ]
    return mock_result


# ---------------------------------------------------------------------------
# TestLeadClassifier — 5 parametrized leads
# ---------------------------------------------------------------------------

# Each tuple: (company, message, expected_stage_options)
# expected_stage_options covers the range of valid LLM outputs so tests aren't
# brittle against minor LLM variation in score.
TEST_LEADS = [
    (
        "Big Corp",
        "We need AI CRM for 500 agents, budget $500k, start next week",
        ["hot_lead", "proposal", "escalated"],  # high score, possibly flagged
    ),
    (
        "Small Startup",
        "Just curious about pricing, no budget yet",
        ["nurture", "disqualified"],  # low urgency, no budget
    ),
    (
        "Gulf Properties",
        "Interested in your real estate CRM, 200 agents, approved budget",
        ["hot_lead", "nurture", "escalated"],  # good signal
    ),
    (
        "Spam LLC",
        "Make money fast, click here now!!!!",
        ["disqualified", "escalated"],  # obvious low quality
    ),
    (
        "TechCo",
        "Evaluating CRM solutions for Q3, 50 person team",
        ["nurture", "hot_lead"],  # mid-range
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("company,message,expected_stages", TEST_LEADS)
async def test_lead_classifier(company, message, expected_stages, initialized_db, monkeypatch):
    """
    Run classify_lead for each parametrized input.

    Mocks:
      - LLM complete() → deterministic responses keyed by expected stage
      - RAG query()    → fixed 3-chunk response

    Asserts:
      - result["stage"] is in expected_stages
      - result["score"] is 0-100
      - result["run_id"] is a non-empty string
      - run is logged to agent_runs table
    """
    # Mock LLM to return responses that produce a predictable score
    # We return different scores based on which lead we're testing
    score_map = {
        "Big Corp":       "85",   # → hot_lead (unless red flags)
        "Small Startup":  "30",   # → disqualified
        "Gulf Properties": "75",  # → nurture (unless red flags)
        "Spam LLC":       "5",    # → disqualified
        "TechCo":         "65",   # → nurture
    }
    score_response = score_map.get(company, "50")

    call_count = {"n": 0}

    async def mock_complete(prompt, system="", model=None):
        call_count["n"] += 1
        n = call_count["n"]
        if n == 1:
            return "demo request"           # classify_intent
        elif n == 2:
            return (                        # enrich_lead
                f"industry: Technology\n"
                f"company_size_estimate: mid-market\n"
                f"urgency: this_quarter\n"
                f"red_flags: none"
            )
        elif n == 3:
            return score_response           # score_lead
        else:
            return "fallback"

    mock_rag_result = make_rag_mock()

    monkeypatch.setattr("api.agents.lead_agent.complete", mock_complete)
    monkeypatch.setattr(
        "api.agents.lead_agent.rag_query",
        AsyncMock(return_value=mock_rag_result),
    )

    from api.agents.lead_agent import classify_lead

    result = await classify_lead(
        company=company,
        contact_name="Test Contact",
        contact_email="test@example.com",
        source="Website",
        message=message,
    )

    assert result["stage"] in expected_stages, (
        f"Expected stage in {expected_stages}, got '{result['stage']}' "
        f"(score={result['score']}, company={company})"
    )
    assert 0 <= result["score"] <= 100, f"Score {result['score']} out of 0-100 range"
    assert result["run_id"], "run_id should be a non-empty string"

    # Verify the run was logged to agent_runs
    async with aiosqlite.connect(initialized_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT status FROM agent_runs WHERE run_id = ?",
            (result["run_id"],),
        )
        row = await cursor.fetchone()

    assert row is not None, "agent_runs row should exist after classify_lead"
    assert row["status"] == "completed", f"Expected status=completed, got {row['status']}"


# ---------------------------------------------------------------------------
# TestFollowupWriter — 1 test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_followup_writer(initialized_db, monkeypatch):
    """
    Seed a deal into the temp DB, call write_followup, assert quality.

    Mocks:
      - LLM complete() → draft email + review score ≥ 70 (no retry needed)
      - RAG query()    → fixed 3-chunk response

    Asserts:
      - result["draft"] is a non-empty string
      - result["draft"] contains the contact name (personalised)
      - result["review_score"] is 0-100
      - result["run_id"] is a non-empty string
      - run is logged to agent_runs with status=completed
    """
    # Seed lead + deal into the temp DB
    lead_id = str(uuid4())
    deal_id = str(uuid4())

    async with aiosqlite.connect(initialized_db) as db:
        await db.execute(
            "INSERT INTO leads (id, company, contact_name, contact_email, source, stage, score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lead_id, "Gulf Properties LLC", "Ahmed Al-Mansouri",
             "ahmed@gulf-properties.ae", "Website", "proposal", 85),
        )
        await db.execute(
            "INSERT INTO deals (id, lead_id, stage, value, owner, last_contact) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (deal_id, lead_id, "proposal", 50000.0, "Sales Team"),
        )
        await db.commit()

    draft_text = (
        "Dear Ahmed,\n\n"
        "I hope this message finds you well. Following our recent conversation about "
        "the CRM deployment for Gulf Properties LLC, I wanted to reach out with a "
        "tailored proposal for your 200-agent team.\n\n"
        "Would you be available for a 30-minute call this week to discuss next steps?\n\n"
        "Best regards,\nNexus Team"
    )

    call_count = {"n": 0}

    async def mock_complete(prompt, system="", model=None):
        call_count["n"] += 1
        n = call_count["n"]
        if n == 1:
            return draft_text          # draft_email
        elif n == 2:
            return "SCORE: 92\nNOTES: Well personalised, clear CTA, under 200 words."
        else:
            return draft_text          # fallback

    mock_rag_result = make_rag_mock()

    monkeypatch.setattr("api.agents.followup_agent.complete", mock_complete)
    monkeypatch.setattr(
        "api.agents.followup_agent.rag_query",
        AsyncMock(return_value=mock_rag_result),
    )

    from api.agents.followup_agent import write_followup

    result = await write_followup(deal_id=deal_id)

    assert result["draft"], "draft should be a non-empty string"
    assert "Ahmed" in result["draft"], "draft should be personalised with contact name"
    assert 0 <= result["review_score"] <= 100, (
        f"review_score {result['review_score']} out of 0-100 range"
    )
    assert result["run_id"], "run_id should be a non-empty string"

    # Verify the run was logged
    async with aiosqlite.connect(initialized_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT status, agent_name FROM agent_runs WHERE run_id = ?",
            (result["run_id"],),
        )
        row = await cursor.fetchone()

    assert row is not None, "agent_runs row should exist after write_followup"
    assert row["status"] == "completed"
    assert row["agent_name"] == "followup_writer"


# ---------------------------------------------------------------------------
# TestPipelineReporter — 1 test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_reporter(initialized_db, monkeypatch):
    """
    Seed some leads and deals, call generate_report, assert KPI structure.

    Mocks:
      - LLM complete() → fixed 3-paragraph digest string

    Asserts:
      - result["kpis"] has all 4 expected keys
      - result["digest"] is a non-empty string
      - result["bottlenecks"] is a list (may be empty with clean seed data)
      - result["run_id"] is a non-empty string
      - run is logged to agent_runs with status=completed
    """
    # Seed representative pipeline data into the temp DB
    async with aiosqlite.connect(initialized_db) as db:
        # 3 leads across different stages
        for stage, score in [("hot_lead", 85), ("nurture", 60), ("new_lead", 0)]:
            lead_id = str(uuid4())
            await db.execute(
                "INSERT INTO leads (id, company, contact_name, source, stage, score) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (lead_id, f"Company {stage}", "Contact", "Website", stage, score),
            )
            # Attach a deal to hot_lead and nurture
            if stage != "new_lead":
                deal_id = str(uuid4())
                await db.execute(
                    "INSERT INTO deals (id, lead_id, stage, value, owner) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (deal_id, lead_id, stage, 25000.0, "Sales"),
                )
        await db.commit()

    fixed_digest = (
        "The pipeline is in a healthy early-growth state with leads distributed across "
        "hot, nurture, and new stages. Conversion rate stands at 0% as no deals have "
        "closed yet, which is expected at this stage.\n\n"
        "Total pipeline value is $50,000.00 across 2 active deals. "
        "Average deal age is under 1 day given the fresh data. "
        "Three leads are tracked: 1 hot lead, 1 in nurture, 1 new.\n\n"
        "Recommended actions: focus on converting the hot lead within 7 days, "
        "enrol the nurture lead in the drip sequence, and qualify the new lead "
        "using the lead classifier agent to determine fit."
    )

    async def mock_complete(prompt, system="", model=None):
        return fixed_digest

    monkeypatch.setattr("api.agents.reporter_agent.complete", mock_complete)

    from api.agents.reporter_agent import generate_report

    result = await generate_report()

    # Assert all 4 KPI keys are present
    expected_kpi_keys = {
        "conversion_rate",
        "avg_deal_age",
        "stage_distribution",
        "total_pipeline_value",
    }
    assert expected_kpi_keys.issubset(set(result["kpis"].keys())), (
        f"Missing KPI keys. Got: {list(result['kpis'].keys())}"
    )

    # Assert digest is non-empty
    assert result["digest"], "digest should be a non-empty string"
    assert len(result["digest"]) > 50, "digest should be a meaningful paragraph, not a stub"

    # Assert bottlenecks is a list (may be empty — depends on seed data)
    assert isinstance(result["bottlenecks"], list), "bottlenecks should be a list"

    # Assert run_id is present
    assert result["run_id"], "run_id should be a non-empty string"

    # Assert stage_distribution reflects our seeded data
    stage_dist = result["kpis"]["stage_distribution"]
    assert stage_dist.get("hot_lead", 0) >= 1, "hot_lead should appear in stage distribution"
    assert stage_dist.get("nurture", 0) >= 1, "nurture should appear in stage distribution"

    # Assert total pipeline value matches seeded deals ($25k × 2 = $50k)
    assert result["kpis"]["total_pipeline_value"] == pytest.approx(50000.0, rel=0.01), (
        f"Expected total_pipeline_value ~50000, got {result['kpis']['total_pipeline_value']}"
    )

    # Verify the run was logged
    async with aiosqlite.connect(initialized_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT status, agent_name FROM agent_runs WHERE run_id = ?",
            (result["run_id"],),
        )
        row = await cursor.fetchone()

    assert row is not None, "agent_runs row should exist after generate_report"
    assert row["status"] == "completed"
    assert row["agent_name"] == "pipeline_reporter"