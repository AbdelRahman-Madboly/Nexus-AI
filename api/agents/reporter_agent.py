"""
api/agents/reporter_agent.py
============================
Pipeline Reporter Agent — Phase 2, Day 8.

Queries the SQLite CRM database, computes 4 KPI sections, identifies bottlenecks
using rule-based logic, and generates a written executive digest via an LLM.
All of this runs as a 5-node LangGraph pipeline.

Why LangGraph for reporting?
  - Each stage is isolated and testable independently.
  - Adding new data sources (n8n, external APIs) in Phase 5 means adding a node,
    not rewriting the function.
  - The agent_runs log gives full audit history of every report generated.

Pipeline:
  query_pipeline_data → compute_kpis → identify_bottlenecks → generate_digest → route_to_output → END
"""

import logging
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from api.agents.graph import log_agent_complete, log_agent_start
from api.database import get_db
from api.llm.llm_router import complete

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------

class ReporterState(TypedDict):
    # Node outputs — filled as the graph runs
    pipeline_data:  dict    # query_pipeline_data — raw SQL results
    kpis:           dict    # compute_kpis — 4 computed KPI sections
    bottlenecks:    list    # identify_bottlenecks — list of bottleneck strings
    digest:         str     # generate_digest — written executive summary
    run_id:         str     # set at graph entry, used for logging


# ---------------------------------------------------------------------------
# Node 1: query_pipeline_data
# ---------------------------------------------------------------------------

async def query_pipeline_data(state: ReporterState) -> dict:
    """
    Run 4 SQL queries against the CRM database and collect raw pipeline data.

    Why query here and compute later? Separating data collection from calculation
    makes each step testable in isolation. The compute_kpis node gets clean data
    without worrying about DB connections or async SQL.

    Queries:
      1. Stage distribution (count of leads per stage)
      2. Average deal age in days
      3. Total deal value grouped by stage
      4. Agent activity in the last 7 days
    """
    logger.info("query_pipeline_data | run_id=%s", state["run_id"])

    stage_counts: dict = {}
    avg_deal_age: float = 0.0
    value_by_stage: dict = {}
    agent_activity: list = []

    try:
        async with get_db() as db:
            # Query 1: stage distribution across leads
            cursor = await db.execute(
                "SELECT stage, COUNT(*) as count FROM leads GROUP BY stage;"
            )
            rows = await cursor.fetchall()
            stage_counts = {row["stage"]: row["count"] for row in rows}

            # Query 2: average deal age in days
            cursor = await db.execute(
                "SELECT AVG((julianday('now') - julianday(created_at))) as avg_age FROM deals;"
            )
            row = await cursor.fetchone()
            avg_deal_age = float(row["avg_age"] or 0.0)

            # Query 3: total deal value by stage
            cursor = await db.execute(
                "SELECT stage, SUM(value) as total_value FROM deals GROUP BY stage;"
            )
            rows = await cursor.fetchall()
            value_by_stage = {
                row["stage"]: float(row["total_value"] or 0.0) for row in rows
            }

            # Query 4: agent activity last 7 days
            cursor = await db.execute(
                """
                SELECT agent_name, status, COUNT(*) as count
                FROM agent_runs
                WHERE started_at > datetime('now', '-7 days')
                GROUP BY agent_name, status;
                """
            )
            rows = await cursor.fetchall()
            agent_activity = [dict(row) for row in rows]

    except Exception as exc:
        # Never crash the reporter if queries fail — return empty data and continue
        logger.warning("query_pipeline_data DB error: %s", exc)

    pipeline_data = {
        "stage_counts":   stage_counts,
        "avg_deal_age":   avg_deal_age,
        "value_by_stage": value_by_stage,
        "agent_activity": agent_activity,
    }

    logger.info(
        "query_pipeline_data | stages=%d | avg_age=%.1f days",
        len(stage_counts), avg_deal_age,
    )
    return {"pipeline_data": pipeline_data}


# ---------------------------------------------------------------------------
# Node 2: compute_kpis
# ---------------------------------------------------------------------------

async def compute_kpis(state: ReporterState) -> dict:
    """
    Compute 4 KPI sections from the raw pipeline data.

    Why compute here and not in query_pipeline_data? Separating collection from
    calculation keeps each node testable in isolation — we can unit-test formulas
    without a database connection.

    KPIs computed:
      1. conversion_rate:      closed_won / (closed_won + closed_lost) * 100
                               Returns 0 if no closed deals exist yet.
      2. avg_deal_age:         From pipeline_data, rounded to 1 decimal place.
      3. stage_distribution:   Dict of stage → count (passed through directly).
      4. total_pipeline_value: Sum of all deal values across all stages.
    """
    logger.info("compute_kpis | run_id=%s", state["run_id"])

    data = state["pipeline_data"]
    stage_counts = data.get("stage_counts", {})
    value_by_stage = data.get("value_by_stage", {})

    # Conversion rate
    closed_won  = stage_counts.get("closed_won", 0)
    closed_lost = stage_counts.get("closed_lost", 0)
    total_closed = closed_won + closed_lost
    conversion_rate = round((closed_won / total_closed * 100), 1) if total_closed > 0 else 0.0

    # Average deal age (already computed by SQL AVG — just round it)
    avg_deal_age = round(data.get("avg_deal_age", 0.0), 1)

    # Stage distribution — direct passthrough of raw counts
    stage_distribution = dict(stage_counts)

    # Total pipeline value — sum all stages
    total_pipeline_value = round(sum(value_by_stage.values()), 2)

    kpis = {
        "conversion_rate":      conversion_rate,
        "avg_deal_age":         avg_deal_age,
        "stage_distribution":   stage_distribution,
        "total_pipeline_value": total_pipeline_value,
    }

    logger.info(
        "compute_kpis | conversion=%.1f%% | avg_age=%.1f days | total_value=%.2f",
        conversion_rate, avg_deal_age, total_pipeline_value,
    )
    return {"kpis": kpis}


# ---------------------------------------------------------------------------
# Node 3: identify_bottlenecks
# ---------------------------------------------------------------------------

async def identify_bottlenecks(state: ReporterState) -> dict:
    """
    Apply rule-based logic to identify pipeline bottlenecks.

    Why rules instead of the LLM here? Bottleneck detection must be deterministic,
    auditable, and fast. Rules give consistent output that can be unit-tested and
    explained to stakeholders. The LLM digest in the next node interprets these
    findings into a narrative.

    Rules applied:
      1. Any stage holds > 40% of all leads → overloaded stage warning
      2. Average deal age > 30 days → deals are aging warning
      3. Conversion rate < 20% (and > 0%) → low conversion warning
      4. new_lead count > hot_lead + nurture combined → qualification bottleneck
    """
    logger.info("identify_bottlenecks | run_id=%s", state["run_id"])

    kpis = state["kpis"]
    stage_dist = kpis.get("stage_distribution", {})
    conversion_rate = kpis.get("conversion_rate", 0.0)
    avg_deal_age = kpis.get("avg_deal_age", 0.0)

    bottlenecks: list = []
    total_leads = sum(stage_dist.values())

    # Rule 1: any single stage holds more than 40% of pipeline
    if total_leads > 0:
        for stage, count in stage_dist.items():
            pct = (count / total_leads) * 100
            if pct > 40:
                bottlenecks.append(
                    f"Stage '{stage}' is overloaded ({pct:.0f}% of pipeline, {count} leads)"
                )

    # Rule 2: deals are aging — average over 30 days suggests stalled pipeline
    if avg_deal_age > 30:
        bottlenecks.append(
            f"Deals aging: average {avg_deal_age:.1f} days in pipeline (threshold: 30 days)"
        )

    # Rule 3: low conversion rate — only flag if there's actual closed deal data
    if 0 < conversion_rate < 20:
        bottlenecks.append(
            f"Low conversion rate: {conversion_rate:.1f}% (threshold: 20%)"
        )

    # Rule 4: qualification bottleneck — more unqualified leads than qualified
    new_leads = stage_dist.get("new_lead", 0)
    hot_leads = stage_dist.get("hot_lead", 0)
    nurture   = stage_dist.get("nurture", 0)
    if new_leads > 0 and new_leads > (hot_leads + nurture):
        bottlenecks.append(
            f"Lead qualification bottleneck: {new_leads} new leads vs "
            f"{hot_leads + nurture} qualified ({hot_leads} hot + {nurture} nurture)"
        )

    logger.info(
        "identify_bottlenecks | run_id=%s | bottlenecks_found=%d",
        state["run_id"], len(bottlenecks),
    )
    return {"bottlenecks": bottlenecks}


# ---------------------------------------------------------------------------
# Node 4: generate_digest
# ---------------------------------------------------------------------------

async def generate_digest(state: ReporterState) -> dict:
    """
    Generate a 3-paragraph executive digest using the LLM.

    Why LLM here and not earlier? The KPIs and bottlenecks are deterministic
    computed values — they don't need LLM interpretation. The digest is where
    the LLM adds genuine value: turning numbers into a narrative that a business
    owner can act on without needing to understand the underlying data model.

    We inject exact numbers into the prompt so the LLM cannot hallucinate them.
    If the LLM call fails, we fall back to a minimal template-generated summary
    so the report endpoint never returns an empty digest.

    Output: 3 paragraphs (no headers, no bullet points)
      Paragraph 1: Overall pipeline health
      Paragraph 2: Key numbers (exact KPI values)
      Paragraph 3: Recommended actions (addresses identified bottlenecks)
    """
    logger.info("generate_digest | run_id=%s", state["run_id"])

    kpis = state["kpis"]
    bottlenecks = state["bottlenecks"]

    bottleneck_text = (
        "\n".join(f"  - {b}" for b in bottlenecks)
        if bottlenecks
        else "  - No critical bottlenecks detected"
    )

    prompt = (
        f"You are a business intelligence analyst writing for a non-technical CEO. "
        f"Write a 3-paragraph executive pipeline digest using ONLY the data provided below. "
        f"Be specific — use the exact numbers. Do not add headers, bullet points, or greetings.\n\n"
        f"KPI Data:\n"
        f"  - Conversion rate: {kpis.get('conversion_rate', 0)}%\n"
        f"  - Average deal age: {kpis.get('avg_deal_age', 0)} days\n"
        f"  - Total pipeline value: ${kpis.get('total_pipeline_value', 0):,.2f}\n"
        f"  - Stage distribution: {kpis.get('stage_distribution', {})}\n\n"
        f"Identified bottlenecks:\n{bottleneck_text}\n\n"
        f"Write exactly 3 paragraphs:\n"
        f"  Paragraph 1: Overall pipeline health — use stage distribution and conversion rate.\n"
        f"  Paragraph 2: Key numbers — reference the specific KPI values above.\n"
        f"  Paragraph 3: Recommended actions — directly address the bottlenecks listed above.\n"
    )

    try:
        digest = await complete(prompt)
        digest = digest.strip()
    except Exception as exc:
        logger.warning("generate_digest LLM call failed: %s", exc)
        # Fallback: minimal template so the report is still useful
        total_leads = sum(kpis.get("stage_distribution", {}).values())
        digest = (
            f"The pipeline currently holds {total_leads} total leads with a conversion rate of "
            f"{kpis.get('conversion_rate', 0)}%. "
            f"Average deal age is {kpis.get('avg_deal_age', 0)} days and total pipeline value "
            f"stands at ${kpis.get('total_pipeline_value', 0):,.2f}. "
            f"{len(bottlenecks)} bottleneck(s) identified: {'; '.join(bottlenecks) if bottlenecks else 'none'}. "
            f"Review the stage distribution and address any overloaded stages promptly."
        )

    logger.info(
        "generate_digest | run_id=%s | digest_length=%d chars",
        state["run_id"], len(digest),
    )
    return {"digest": digest}


# ---------------------------------------------------------------------------
# Node 5: route_to_output
# ---------------------------------------------------------------------------

async def route_to_output(state: ReporterState) -> dict:
    """
    Pass-through node — returns state unchanged.

    Why does this exist? It provides a clean extension point for Phase 5 (n8n):
    adding Slack notifications or email delivery means adding logic here, not
    rewiring the graph. For now it logs completion and returns nothing.
    """
    logger.info(
        "route_to_output | run_id=%s | bottlenecks=%d | digest_ready=%s",
        state["run_id"], len(state.get("bottlenecks", [])), bool(state.get("digest")),
    )
    return {}


# ---------------------------------------------------------------------------
# Compiled graph (module-level singleton — built once on first import)
# ---------------------------------------------------------------------------

def _build_reporter_graph():
    """
    Wire and compile the 5-node Reporter StateGraph.

    Built separately from build_graph() in graph.py because this graph is
    purely linear — no conditional edges — and we want the node names explicit
    for readability. Uses MemorySaver for in-request state isolation.
    """
    builder = StateGraph(ReporterState)

    builder.add_node("query_pipeline_data",  query_pipeline_data)
    builder.add_node("compute_kpis",         compute_kpis)
    builder.add_node("identify_bottlenecks", identify_bottlenecks)
    builder.add_node("generate_digest",      generate_digest)
    builder.add_node("route_to_output",      route_to_output)

    builder.add_edge("query_pipeline_data",  "compute_kpis")
    builder.add_edge("compute_kpis",         "identify_bottlenecks")
    builder.add_edge("identify_bottlenecks", "generate_digest")
    builder.add_edge("generate_digest",      "route_to_output")
    builder.add_edge("route_to_output",      END)

    builder.set_entry_point("query_pipeline_data")

    return builder.compile(checkpointer=MemorySaver())


_reporter_graph = _build_reporter_graph()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_report() -> dict:
    """
    Run the Pipeline Reporter Agent and return a structured KPI report.

    Logs start + end to the agent_runs table. On failure, marks the run as
    'failed' rather than leaving it as 'running'.

    Returns:
        dict with keys:
          - kpis:        dict — conversion_rate, avg_deal_age, stage_distribution,
                         total_pipeline_value
          - bottlenecks: list of bottleneck strings (empty list if none found)
          - digest:      3-paragraph executive summary string
          - run_id:      UUID for trace lookup via GET /api/agents/trace/{run_id}

    Raises:
        Any exception from the graph is re-raised after logging status='failed'.
    """
    run_id = str(uuid4())

    input_data = {"run_id": run_id}
    row_id = await log_agent_start("pipeline_reporter", run_id, input_data)

    initial_state: ReporterState = {
        "pipeline_data": {},
        "kpis":          {},
        "bottlenecks":   [],
        "digest":        "",
        "run_id":        run_id,
    }

    try:
        result = await _reporter_graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": run_id}},
        )

        output = {
            "kpis":        result["kpis"],
            "bottlenecks": result["bottlenecks"],
            "digest":      result["digest"],
            "run_id":      run_id,
        }

        await log_agent_complete(row_id, output, status="completed")
        logger.info(
            "generate_report complete | run_id=%s | kpi_keys=%s | bottlenecks=%d",
            run_id, list(output["kpis"].keys()), len(output["bottlenecks"]),
        )
        return output

    except Exception as exc:
        logger.exception("generate_report failed | run_id=%s | error=%s", run_id, exc)
        await log_agent_complete(row_id, {"error": str(exc)}, status="failed")
        raise