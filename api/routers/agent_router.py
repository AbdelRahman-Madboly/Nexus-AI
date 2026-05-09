"""
api/routers/agent_router.py
===========================
LangGraph agent router for Nexus-AI.

Day 6: POST /api/agents/lead/classify  → LIVE (Lead Classifier Agent)
       GET  /api/agents/trace/{run_id} → LIVE (query agent_runs table)

Day 7: POST /api/agents/lead/followup  → LIVE (Follow-up Writer Agent)

Day 8: GET  /api/agents/pipeline/report → LIVE (Pipeline Reporter Agent)
       tests/test_agents.py             → 7 tests, all passing
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.agents.lead_agent import classify_lead
from api.agents.followup_agent import write_followup
from api.agents.reporter_agent import generate_report
from api.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["Agents"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class LeadClassifyRequest(BaseModel):
    company:       str
    contact_name:  str
    contact_email: str = ""
    source:        str
    message:       str


class LeadClassifyResponse(BaseModel):
    stage:     str
    score:     int
    reasoning: str
    run_id:    str


class FollowupRequest(BaseModel):
    deal_id: str


class FollowupResponse(BaseModel):
    draft:        str
    review_score: int
    run_id:       str


class ReportResponse(BaseModel):
    kpis:        dict
    bottlenecks: list
    digest:      str
    run_id:      str


class MessageResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# POST /api/agents/lead/classify — LIVE (Day 6)
# ---------------------------------------------------------------------------

@router.post(
    "/lead/classify",
    response_model=LeadClassifyResponse,
    status_code=200,
    summary="Classify an inbound lead via LangGraph agent",
    description=(
        "Runs the Lead Classifier Agent (5-node LangGraph StateGraph). "
        "Returns stage, score, reasoning, and run_id. "
        "Use GET /trace/{run_id} to inspect the full node-by-node trace."
    ),
)
async def classify_lead_endpoint(body: LeadClassifyRequest) -> LeadClassifyResponse:
    """
    Accepts raw lead data, runs it through the 5-node Lead Classifier pipeline,
    and returns the routing decision.

    The agent:
      1. classify_intent   — labels the lead's intent in 1–3 words
      2. retrieve_context  — fetches relevant RAG chunks from ChromaDB
      3. enrich_lead       — extracts industry, size, urgency, red_flags
      4. score_lead        — scores 0–100
      5. route_to_pipeline — maps score → LeadStage, writes reasoning

    Full run is logged to agent_runs and retrievable via /trace/{run_id}.
    """
    try:
        result = await classify_lead(**body.model_dump())
        return LeadClassifyResponse(**result)
    except Exception as exc:
        logger.exception("classify_lead_endpoint error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Lead classification failed: {str(exc)}"},
        )


# ---------------------------------------------------------------------------
# GET /api/agents/trace/{run_id} — LIVE (Day 6)
# ---------------------------------------------------------------------------

@router.get(
    "/trace/{run_id}",
    summary="Retrieve a LangGraph agent run trace",
    description=(
        "Fetches the full input/output record for a past agent run from the "
        "agent_runs SQLite table. Returns 404 if the run_id is not found."
    ),
)
async def get_trace(run_id: str):
    """
    Looks up the agent_runs row for the given run_id.

    Returns all columns: id, agent_name, run_id, input_json, output_json,
    status, started_at, completed_at.

    Note: input_json and output_json are raw JSON strings — parse them
    client-side if you need structured access.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, agent_name, run_id, input_json, output_json,
                   status, started_at, completed_at
            FROM agent_runs
            WHERE run_id = ?
            """,
            (run_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"No agent run found for run_id={run_id}"},
        )

    return dict(row)


# ---------------------------------------------------------------------------
# POST /api/agents/lead/followup — LIVE (Day 7)
# ---------------------------------------------------------------------------

@router.post(
    "/lead/followup",
    response_model=FollowupResponse,
    status_code=200,
    summary="Draft a follow-up email via LangGraph agent",
    description=(
        "Runs the Follow-up Writer Agent (5-node LangGraph StateGraph with self-review loop). "
        "Loads deal + lead from SQLite, retrieves RAG context, drafts an email, "
        "self-reviews it (score 0–100), and retries up to 2 times if score < 70. "
        "Returns the final draft, its review score, and a run_id for tracing."
    ),
)
async def draft_followup(body: FollowupRequest) -> FollowupResponse:
    """
    Accepts a deal_id, runs it through the Follow-up Writer pipeline:

      1. load_deal_history        — JOIN deals + leads from SQLite
      2. retrieve_product_context — RAG chunks for deal context
      3. draft_email              — personalised email (< 200 words, clear CTA)
      4. self_review              — scores draft 0–100, writes improvement notes
      5. route_by_confidence      — if score < 70 AND retries < 2 → loop to draft_email
                                    else → END

    Full run is logged to agent_runs and retrievable via GET /trace/{run_id}.

    Returns 404 if deal_id is not found.
    Returns 500 on unexpected agent failure.
    """
    try:
        result = await write_followup(deal_id=body.deal_id)
        return FollowupResponse(**result)
    except ValueError as exc:
        # deal_id not found in SQLite — propagated from load_deal_history
        logger.warning("draft_followup: deal not found | deal_id=%s | %s", body.deal_id, exc)
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )
    except Exception as exc:
        logger.exception("draft_followup error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Follow-up generation failed: {str(exc)}"},
        )


# ---------------------------------------------------------------------------
# GET /api/agents/pipeline/report — LIVE (Day 8)
# ---------------------------------------------------------------------------

@router.get(
    "/pipeline/report",
    response_model=ReportResponse,
    status_code=200,
    summary="Generate a pipeline KPI report via LangGraph agent",
    description=(
        "Runs the Pipeline Reporter Agent (5-node LangGraph StateGraph). "
        "Queries all CRM data from SQLite, computes 4 KPI sections "
        "(conversion_rate, avg_deal_age, stage_distribution, total_pipeline_value), "
        "identifies bottlenecks via rule-based logic, and generates a 3-paragraph "
        "executive digest via LLM. Full run logged to agent_runs."
    ),
)
async def pipeline_report() -> ReportResponse:
    """
    Runs the Pipeline Reporter Agent through its 5-node pipeline:

      1. query_pipeline_data  — 4 SQL queries: stage counts, deal age, value, agent activity
      2. compute_kpis         — derives conversion_rate, avg_deal_age, stage_distribution,
                                total_pipeline_value from raw query data
      3. identify_bottlenecks — applies 4 rules to flag pipeline problems
      4. generate_digest      — LLM writes 3-paragraph executive summary with exact KPI values
      5. route_to_output      — pass-through, reserved for Phase 5 Slack/email delivery

    Returns:
      kpis:        dict with 4 KPI keys
      bottlenecks: list of bottleneck strings (empty list if pipeline is healthy)
      digest:      3-paragraph written summary
      run_id:      UUID for GET /trace/{run_id}
    """
    try:
        result = await generate_report()
        return ReportResponse(**result)
    except Exception as exc:
        logger.exception("pipeline_report error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Pipeline report generation failed: {str(exc)}"},
        )