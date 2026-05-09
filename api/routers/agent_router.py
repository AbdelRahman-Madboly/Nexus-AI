"""
api/routers/agent_router.py
===========================
LangGraph agent router for Nexus-AI.

Day 6 update:
  - POST /api/agents/lead/classify  → LIVE (Lead Classifier Agent)
  - GET  /api/agents/trace/{run_id} → LIVE (query agent_runs table)

Still 501 (implemented in later days):
  - POST /api/agents/lead/followup   → Phase 2, Day 7
  - GET  /api/agents/pipeline/report → Phase 2, Day 8
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.agents.lead_agent import classify_lead
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
# POST /api/agents/lead/classify — LIVE
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
# GET /api/agents/trace/{run_id} — LIVE
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
# POST /api/agents/lead/followup — 501 until Day 7
# ---------------------------------------------------------------------------

@router.post(
    "/lead/followup",
    response_model=MessageResponse,
    status_code=501,
    summary="Draft a follow-up email via LangGraph agent",
    description="Phase 2, Day 7 — not yet implemented.",
)
async def draft_followup(body: FollowupRequest) -> JSONResponse:
    """
    Will run the Follow-up Writer Agent (5 nodes + self-review loop, max 2 retries).
    Returns draft, review_score, and run_id.  Built in Phase 2, Day 7.
    """
    return JSONResponse(
        status_code=501,
        content={"detail": "Follow-up Writer Agent not yet implemented"},
    )


# ---------------------------------------------------------------------------
# GET /api/agents/pipeline/report — 501 until Day 8
# ---------------------------------------------------------------------------

@router.get(
    "/pipeline/report",
    response_model=MessageResponse,
    status_code=501,
    summary="Generate a pipeline KPI report via LangGraph agent",
    description="Phase 2, Day 8 — not yet implemented.",
)
async def pipeline_report() -> JSONResponse:
    """
    Will run the Pipeline Reporter Agent (4 KPI sections + bottleneck analysis).
    Built in Phase 2, Day 8.
    """
    return JSONResponse(
        status_code=501,
        content={"detail": "Pipeline Reporter Agent not yet implemented"},
    )