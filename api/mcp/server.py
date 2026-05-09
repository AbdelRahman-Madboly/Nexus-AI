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

# ===========================================================================
# Phase 3, Day 10 — 4 Action Tools
# ===========================================================================

# ---------------------------------------------------------------------------
# Tool 7: nexus_update_deal_stage
# ---------------------------------------------------------------------------

@mcp.tool()
async def nexus_update_deal_stage(
    deal_id: str,
    new_stage: str,
    owner: str = "",
) -> dict:
    """
    Update the stage of a deal in the Nexus CRM pipeline.

    Args:
        deal_id: UUID of the deal to update.
        new_stage: New stage to set. Valid values: new_lead, hot_lead,
                   nurture, proposal, closed_won, closed_lost,
                   disqualified, escalated.
        owner: Optional — update the deal owner at the same time.

    Returns:
        Dict with keys:
          - "success": True if updated, False if deal not found or invalid stage
          - "deal_id": the deal_id that was updated
          - "new_stage": the stage that was set
          - "message": human-readable confirmation or error
    """
    from api.models.crm_models import LeadStage

    # Validate stage against the enum
    valid_stages = [s.value for s in LeadStage]
    if new_stage not in valid_stages:
        return {
            "success":   False,
            "deal_id":   deal_id,
            "new_stage": new_stage,
            "message":   f"Invalid stage: '{new_stage}'. Valid values: {', '.join(valid_stages)}",
        }

    async with get_db() as db:
        # Verify deal exists
        cursor = await db.execute(
            "SELECT id FROM deals WHERE id = ?", (deal_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return {
                "success":   False,
                "deal_id":   deal_id,
                "new_stage": new_stage,
                "message":   "Deal not found",
            }

        # Build UPDATE — always set stage + updated_at, optionally owner
        if owner:
            await db.execute(
                "UPDATE deals SET stage = ?, owner = ?, updated_at = datetime('now') WHERE id = ?",
                (new_stage, owner, deal_id),
            )
        else:
            await db.execute(
                "UPDATE deals SET stage = ?, updated_at = datetime('now') WHERE id = ?",
                (new_stage, deal_id),
            )
        await db.commit()

    logger.info("nexus_update_deal_stage | deal_id=%s | new_stage=%s", deal_id, new_stage)
    return {
        "success":   True,
        "deal_id":   deal_id,
        "new_stage": new_stage,
        "message":   "Deal updated successfully",
    }


# ---------------------------------------------------------------------------
# Tool 8: nexus_ingest_document
# ---------------------------------------------------------------------------

@mcp.tool()
async def nexus_ingest_document(
    source: str,
    doc_type: str = "auto",
) -> dict:
    """
    Ingest a document into the Nexus knowledge base.

    Supports URLs (http/https), file paths (.pdf, .docx, .md, .txt),
    and raw text strings. After ingestion, the document is searchable
    via nexus_search_knowledge.

    Args:
        source: URL, file path, or raw text to ingest.
        doc_type: Document type hint. Options: url, pdf, docx, md, text, auto.
                  Use "auto" to let Nexus detect the type automatically.

    Returns:
        Dict with keys:
          - "source": the source that was ingested
          - "doc_type": the detected or specified document type
          - "chunk_count": number of chunks stored in ChromaDB
          - "duration_ms": time taken in milliseconds
          - "errors": list of any non-fatal errors encountered
    """
    try:
        # Lazy import — avoids circular imports and heavy ML deps at startup
        from api.rag.ingestor import ingest

        # ingest() is async — it awaits embed calls and runs ChromaDB in executor internally
        result = await ingest(source=source, doc_type=doc_type, metadata={})

        return {
            "source":      result.source,
            "doc_type":    result.doc_type,
            "chunk_count": result.chunk_count,
            "duration_ms": result.duration_ms,
            "errors":      result.errors,
        }
    except Exception as exc:
        logger.error("nexus_ingest_document failed: %s", exc)
        return {
            "source":      source,
            "doc_type":    doc_type,
            "chunk_count": 0,
            "duration_ms": 0,
            "errors":      [str(exc)],
        }


# ---------------------------------------------------------------------------
# Tool 9: nexus_schedule_followup
# ---------------------------------------------------------------------------

@mcp.tool()
async def nexus_schedule_followup(deal_id: str) -> dict:
    """
    Generate a personalised follow-up email draft for a deal using the
    Nexus Follow-up Writer LangGraph agent.

    The agent loads the deal history, retrieves relevant product context
    from the knowledge base, drafts an email, and self-reviews it
    (retrying up to 2 times if quality score is below 70).

    Args:
        deal_id: UUID of the deal to write a follow-up for.

    Returns:
        Dict with keys:
          - "draft": the email body ready to send
          - "review_score": quality score 0-100 from the self-review node
          - "run_id": the agent run UUID (use with nexus_agent_runs to inspect the trace)
          - "error": present only if the agent failed (e.g. deal not found)
    """
    try:
        # Lazy import — prevents circular imports at module load time
        from api.agents.followup_agent import write_followup

        result = await write_followup(deal_id=deal_id)
        return {
            "draft":        result["draft"],
            "review_score": result["review_score"],
            "run_id":       result["run_id"],
        }
    except ValueError as exc:
        # Deal not found — expected error, return gracefully
        logger.warning("nexus_schedule_followup | deal not found: %s", exc)
        return {
            "draft":        "",
            "review_score": 0,
            "run_id":       "",
            "error":        str(exc),
        }
    except Exception as exc:
        logger.error("nexus_schedule_followup failed: %s", exc)
        return {
            "draft":        "",
            "review_score": 0,
            "run_id":       "",
            "error":        f"Agent failed: {str(exc)}",
        }


# ---------------------------------------------------------------------------
# Tool 10: nexus_pipeline_kpis
# ---------------------------------------------------------------------------

@mcp.tool()
async def nexus_pipeline_kpis() -> dict:
    """
    Run the Nexus Pipeline Reporter agent to generate a full KPI report.

    This triggers the full 5-node LangGraph pipeline:
    SQL queries → KPI computation → bottleneck detection → LLM executive digest.

    Takes 5-15 seconds depending on LLM backend (Gemini free tier: ~8s).
    For a faster snapshot without LLM, use nexus_pipeline_summary instead.

    Returns:
        Dict with keys:
          - "kpis": {conversion_rate, avg_deal_age, stage_distribution, total_pipeline_value}
          - "bottlenecks": list of identified bottleneck strings
          - "digest": LLM-written 3-paragraph executive summary
          - "run_id": the agent run UUID
    """
    try:
        # Lazy import — prevents circular imports and agent/LangGraph startup cost at import time
        from api.agents.reporter_agent import generate_report

        result = await generate_report()
        return result
    except Exception as exc:
        logger.error("nexus_pipeline_kpis failed: %s", exc)
        return {
            "kpis":        {},
            "bottlenecks": [],
            "digest":      f"Report failed: {str(exc)}",
            "run_id":      "",
        }