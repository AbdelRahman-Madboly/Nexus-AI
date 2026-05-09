"""
api/routers/mcp_router.py
=========================
MCP (Model Context Protocol) router for Nexus-AI.

Phase 3, Day 9 — GET /api/mcp/tools is now LIVE.
  Returns all registered FastMCP tool names and their docstrings.
  Count reflects only the tools registered at import time:
    Day 9:  6 tools (data/knowledge)
    Day 10: 10 tools (+ 4 action tools)

FastMCP 3.x note:
  mcp.list_tools() is the official public async API for introspecting tools.
  The old mcp._tool_manager._tools internal path does not exist in fastmcp 3.x.
  Always use await mcp.list_tools() — it returns a list of Tool objects with
  .name and .description attributes.

NOTE — SSE transport:
  The Claude Desktop SSE connection endpoint is NOT registered here.
  It is mounted in api/main.py via:
      app.mount("/mcp", mcp.http_app(path="/sse", transport="sse"))
  This exposes the MCP server at http://localhost:8000/mcp/sse
  which is the URL that goes in claude_desktop_config.json.
  Keeping the SSE mount out of this router avoids Starlette route conflicts.
"""

import logging

from fastapi import APIRouter

from api.mcp.server import mcp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["MCP"])


# ---------------------------------------------------------------------------
# GET /api/mcp/tools — LIVE (Day 9)
# ---------------------------------------------------------------------------

@router.get(
    "/tools",
    summary="List all registered MCP tools",
    description=(
        "Returns the names and descriptions of all FastMCP tools currently "
        "registered with the Nexus-AI MCP server. "
        "Day 9: 6 data/knowledge tools. Day 10: 10 tools (+ 4 action tools)."
    ),
)
async def list_mcp_tools() -> dict:
    """
    Introspect the FastMCP tool registry and return all registered tools.

    Uses the official fastmcp 3.x public API: await mcp.list_tools()
    Returns Tool objects with .name and .description attributes.

    The tool list grows as phases complete:
      Day 9  -> 6 tools: nexus_query_leads, nexus_query_deals,
                         nexus_get_deal_history, nexus_search_knowledge,
                         nexus_pipeline_summary, nexus_agent_runs
      Day 10 -> 10 tools: + nexus_update_deal_stage, nexus_ingest_document,
                            nexus_schedule_followup, nexus_pipeline_kpis
    """
    try:
        tool_list = await mcp.list_tools()
        tools = [
            {
                "name":        t.name,
                "description": (t.description or "").strip(),
            }
            for t in tool_list
        ]
        return {"tools": tools, "count": len(tools)}

    except Exception as exc:
        logger.error("list_mcp_tools failed: %s", exc)
        return {"tools": [], "count": 0, "error": str(exc)}