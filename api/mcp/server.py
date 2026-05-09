"""
api/mcp/server.py
=================
FastMCP server for Nexus-AI.

Phase 3, Day 9  — server foundation + 6 data/knowledge tools.
Phase 3, Day 10 — 4 action tools added (nexus_update_deal_stage,
                  nexus_ingest_document, nexus_schedule_followup,
                  nexus_pipeline_kpis).

The `mcp` singleton is imported by:
  - api/routers/mcp_router.py  → GET /api/mcp/tools (tool registry endpoint)
  - api/main.py                → app.mount("/mcp", mcp.sse_app())

Rules enforced here:
  - All DB access goes through get_db() — never import aiosqlite directly.
  - RAG and agent imports are LAZY (inside the function body) to prevent
    circular imports at module load time.
  - Every tool returns a typed dict or list[dict]. No raw strings.
  - logger.error() inside every except block. Never print().
"""

import logging
from fastmcp import FastMCP
from api.database import get_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastMCP server singleton
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="Nexus-AI",
    instructions="""
    You are connected to Nexus-AI — a business operations platform.
    Use these tools to query leads, deals, knowledge base, and pipeline data.
    Always use the provided tools for database access and never invent data.
    """,
)


# ---------------------------------------------------------------------------
# Tool 1: nexus_query_leads
# ---------------------------------------------------------------------------

@mcp.tool()
async def nexus_query_leads(
    stage: str = "",
    limit: int = 20,
) -> list[dict]:
    """
    Query leads from the Nexus CRM.

    Args:
        stage: Filter by lead stage. Options: new_lead, hot_lead, nurture,
               proposal, closed_won, closed_lost, disqualified, escalated.
               Leave empty to return all leads.
        limit: Maximum number of leads to return (default 20, max 100).

    Returns:
        List of lead records with id, company, contact_name, contact_email,
        source, stage, score, created_at, updated_at.
    """
    limit = min(limit, 100)

    async with get_db() as db:
        if stage:
            cursor = await db.execute(
                """
                SELECT id, company, contact_name, contact_email,
                       source, stage, score, created_at, updated_at
                FROM leads
                WHERE stage = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (stage, limit),
            )
        else:
            cursor = await db.execute(
                """
                SELECT id, company, contact_name, contact_email,
                       source, stage, score, created_at, updated_at
                FROM leads
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        rows = await cursor.fetchall()

    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tool 2: nexus_query_deals
# ---------------------------------------------------------------------------

@mcp.tool()
async def nexus_query_deals(
    stage: str = "",
    owner: str = "",
    limit: int = 20,
) -> list[dict]:
    """
    Query deals from the Nexus CRM pipeline.

    Args:
        stage: Filter by deal stage (leave empty for all).
        owner: Filter by deal owner name (leave empty for all).
        limit: Maximum deals to return (default 20, max 100).

    Returns:
        List of deal records joined with lead company name.
        Fields: id, lead_id, company (from leads), stage, value, owner,
                last_contact, created_at, updated_at.
    """
    limit = min(limit, 100)

    base_query = """
        SELECT deals.id, deals.lead_id, leads.company, deals.stage,
               deals.value, deals.owner, deals.last_contact,
               deals.created_at, deals.updated_at
        FROM deals
        JOIN leads ON deals.lead_id = leads.id
    """

    conditions = []
    params: list = []

    if stage:
        conditions.append("deals.stage = ?")
        params.append(stage)
    if owner:
        conditions.append("deals.owner = ?")
        params.append(owner)

    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    base_query += " ORDER BY deals.created_at DESC LIMIT ?"
    params.append(limit)

    async with get_db() as db:
        cursor = await db.execute(base_query, params)
        rows = await cursor.fetchall()

    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tool 3: nexus_get_deal_history
# ---------------------------------------------------------------------------

@mcp.tool()
async def nexus_get_deal_history(deal_id: str) -> dict:
    """
    Get the full history of a specific deal including the associated lead.

    Args:
        deal_id: The UUID of the deal to retrieve.

    Returns:
        A dict with two keys:
          - "deal": the deal record
          - "lead": the associated lead record
        Returns {"error": "Deal not found"} if deal_id does not exist.
    """
    async with get_db() as db:
        deal_cursor = await db.execute(
            "SELECT * FROM deals WHERE id = ?",
            (deal_id,),
        )
        deal_row = await deal_cursor.fetchone()

        if deal_row is None:
            return {"error": "Deal not found"}

        deal = dict(deal_row)

        lead_cursor = await db.execute(
            "SELECT * FROM leads WHERE id = ?",
            (deal["lead_id"],),
        )
        lead_row = await lead_cursor.fetchone()
        lead = dict(lead_row) if lead_row else {}

    return {"deal": deal, "lead": lead}


# ---------------------------------------------------------------------------
# Tool 4: nexus_search_knowledge
# ---------------------------------------------------------------------------

@mcp.tool()
async def nexus_search_knowledge(
    query: str,
    top_k: int = 3,
) -> dict:
    """
    Search the Nexus knowledge base using hybrid RAG retrieval.

    Searches the ChromaDB vector store using semantic + BM25 hybrid search
    with cross-encoder reranking. Returns the most relevant chunks and an
    LLM-generated answer grounded in the retrieved context.

    Args:
        query: The search question or topic.
        top_k: Number of source chunks to retrieve (default 3, max 5).

    Returns:
        Dict with keys:
          - "answer": LLM-generated answer citing the retrieved chunks
          - "sources": list of {id, text, metadata, score} dicts
          - "latency_ms": retrieval + generation time in milliseconds
    """
    top_k = min(top_k, 5)

    try:
        # Lazy import — avoids circular import at module load time
        from api.rag.retriever import query as rag_query
        result = await rag_query(q=query, top_k=top_k, stream=False)
        return {
            "answer": result.answer,
            "sources": result.sources,
            "latency_ms": result.latency_ms,
        }
    except Exception as exc:
        logger.error("nexus_search_knowledge failed: %s", exc)
        return {
            "answer": "Knowledge base unavailable",
            "sources": [],
            "latency_ms": 0,
        }


# ---------------------------------------------------------------------------
# Tool 5: nexus_pipeline_summary
# ---------------------------------------------------------------------------

@mcp.tool()
async def nexus_pipeline_summary() -> dict:
    """
    Get a quick summary of the current pipeline state.

    Returns counts per stage for both leads and deals, plus total pipeline
    value. This is a fast DB-only query — no LLM call, no agent invocation.
    Use nexus_pipeline_kpis (Day 10) for the full KPI report with digest.

    Returns:
        Dict with keys:
          - "lead_counts": {stage: count} for all stages
          - "deal_counts": {stage: count} for all deal stages
          - "total_deal_value": sum of all deal values
          - "total_leads": total lead count
          - "total_deals": total deal count
    """
    async with get_db() as db:
        lead_cursor = await db.execute(
            "SELECT stage, COUNT(*) as count FROM leads GROUP BY stage"
        )
        lead_rows = await lead_cursor.fetchall()

        deal_cursor = await db.execute(
            "SELECT stage, COUNT(*) as count FROM deals GROUP BY stage"
        )
        deal_rows = await deal_cursor.fetchall()

        value_cursor = await db.execute(
            "SELECT COALESCE(SUM(value), 0) as total FROM deals"
        )
        value_row = await value_cursor.fetchone()

    lead_counts = {row["stage"]: row["count"] for row in lead_rows}
    deal_counts = {row["stage"]: row["count"] for row in deal_rows}
    total_deal_value = float(value_row["total"]) if value_row else 0.0

    return {
        "lead_counts":      lead_counts,
        "deal_counts":      deal_counts,
        "total_deal_value": total_deal_value,
        "total_leads":      sum(lead_counts.values()),
        "total_deals":      sum(deal_counts.values()),
    }


# ---------------------------------------------------------------------------
# Tool 6: nexus_agent_runs
# ---------------------------------------------------------------------------

@mcp.tool()
async def nexus_agent_runs(
    agent_name: str = "",
    status: str = "",
    limit: int = 10,
) -> list[dict]:
    """
    Query recent agent run logs from the Nexus system.

    Args:
        agent_name: Filter by agent name. Options: lead_classifier,
                    followup_writer, pipeline_reporter.
                    Leave empty to return runs from all agents.
        status: Filter by status. Options: running, completed, failed.
                Leave empty to return all statuses.
        limit: Maximum runs to return (default 10, max 50).

    Returns:
        List of agent run records: run_id, agent_name, status,
        started_at, completed_at, plus truncated input/output summaries
        (first 200 chars of each JSON to keep responses readable).
    """
    limit = min(limit, 50)

    base_query = """
        SELECT run_id, agent_name, status, started_at, completed_at,
               input_json, output_json
        FROM agent_runs
    """

    conditions = []
    params: list = []

    if agent_name:
        conditions.append("agent_name = ?")
        params.append(agent_name)
    if status:
        conditions.append("status = ?")
        params.append(status)

    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    base_query += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)

    async with get_db() as db:
        cursor = await db.execute(base_query, params)
        rows = await cursor.fetchall()

    return [
        {
            "run_id":         row["run_id"],
            "agent_name":     row["agent_name"],
            "status":         row["status"],
            "started_at":     row["started_at"],
            "completed_at":   row["completed_at"],
            "input_preview":  (row["input_json"]  or "")[:200],
            "output_preview": (row["output_json"] or "")[:200],
        }
        for row in rows
    ]