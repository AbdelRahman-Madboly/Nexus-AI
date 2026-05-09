"""
api/routers/mcp_router.py
=========================
MCP (Model Context Protocol) router for Nexus-AI.

Phase 0 — placeholder endpoint.
Real implementation (FastMCP server with 10 tools across 4 groups)
is built in Phase 3, Day 10.

Endpoints:
  GET /api/mcp/tools → 501 until Phase 3
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/mcp", tags=["MCP"])


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------

class MessageResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/tools",
    response_model=MessageResponse,
    status_code=501,
    summary="List all available MCP tools",
    description="Phase 3 — not yet implemented.",
)
async def list_tools() -> JSONResponse:
    """
    Returns all 10 FastMCP tools across 4 groups:
      CRM         — nexus_query_leads, nexus_query_deals,
                    nexus_get_deal_history, nexus_update_deal_stage
      Knowledge   — nexus_search_knowledge, nexus_ingest_document
      Communications — nexus_draft_email, nexus_schedule_followup
      Analytics   — nexus_pipeline_kpis, nexus_agent_runs

    Built in Phase 3, Day 10.
    Claude Desktop connects via claude_desktop_config.json.
    """
    return JSONResponse(
        status_code=501,
        content={"detail": "MCP tool registry not yet implemented"},
    )