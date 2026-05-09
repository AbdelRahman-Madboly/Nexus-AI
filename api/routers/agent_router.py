"""
api/routers/agent_router.py
===========================
LangGraph agent router for Nexus-AI.

Phase 0 — placeholder endpoints.
Real implementation (Lead Classifier, Follow-up Writer, Pipeline Reporter)
is built in Phase 2, Days 6–9.

Endpoints:
  POST /api/agents/lead/classify    → 501 until Phase 2
  POST /api/agents/lead/followup    → 501 until Phase 2
  GET  /api/agents/pipeline/report  → 501 until Phase 2
  GET  /api/agents/trace/{run_id}   → 501 until Phase 2
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/agents", tags=["Agents"])


# ---------------------------------------------------------------------------
# Shared response model
# ---------------------------------------------------------------------------

class MessageResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# Request models (typed, even for placeholders)
# ---------------------------------------------------------------------------

class LeadClassifyRequest(BaseModel):
    company: str
    contact_name: str = ""
    contact_email: str = ""
    source: str = ""
    message: str = ""


class FollowupRequest(BaseModel):
    lead_id: str
    deal_id: str = ""
    tone: str = "professional"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/lead/classify",
    response_model=MessageResponse,
    status_code=501,
    summary="Classify an inbound lead via LangGraph agent",
    description="Phase 2 — not yet implemented.",
)
async def classify_lead(body: LeadClassifyRequest) -> JSONResponse:
    """
    Runs the Lead Classifier Agent (5-node LangGraph StateGraph).
    Returns stage, score, reasoning, and run_id.  Built in Phase 2, Day 6.
    """
    return JSONResponse(
        status_code=501,
        content={"detail": "Lead Classifier Agent not yet implemented"},
    )


@router.post(
    "/lead/followup",
    response_model=MessageResponse,
    status_code=501,
    summary="Draft a follow-up email via LangGraph agent",
    description="Phase 2 — not yet implemented.",
)
async def draft_followup(body: FollowupRequest) -> JSONResponse:
    """
    Runs the Follow-up Writer Agent with a self-review loop (max 2 retries).
    Returns draft, review_score, and run_id.  Built in Phase 2, Day 8.
    """
    return JSONResponse(
        status_code=501,
        content={"detail": "Follow-up Writer Agent not yet implemented"},
    )


@router.get(
    "/pipeline/report",
    response_model=MessageResponse,
    status_code=501,
    summary="Generate a pipeline KPI report via LangGraph agent",
    description="Phase 2 — not yet implemented.",
)
async def pipeline_report() -> JSONResponse:
    """
    Runs the Pipeline Reporter Agent (4 KPI sections + bottleneck analysis).
    Built in Phase 2, Day 9.
    """
    return JSONResponse(
        status_code=501,
        content={"detail": "Pipeline Reporter Agent not yet implemented"},
    )


@router.get(
    "/trace/{run_id}",
    response_model=MessageResponse,
    status_code=501,
    summary="Retrieve a LangGraph agent run trace",
    description="Phase 2 — not yet implemented.",
)
async def get_trace(run_id: str) -> JSONResponse:
    """
    Fetches the full node-by-node trace for a past agent run from SQLite.
    Returns nodes, states, and completed_at.  Built in Phase 2, Day 6.
    """
    return JSONResponse(
        status_code=501,
        content={"detail": f"Agent trace not yet implemented (run_id={run_id})"},
    )