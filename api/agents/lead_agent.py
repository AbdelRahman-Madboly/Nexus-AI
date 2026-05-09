"""
api/agents/lead_agent.py
========================
Lead Classifier Agent for Nexus-AI.

A 5-node LangGraph StateGraph that takes a raw inbound lead and produces:
  - stage:     Which pipeline stage the lead belongs in (LeadStage enum value)
  - score:     Quality score 0–100
  - reasoning: Explanation of the routing decision
  - run_id:    UUID for trace lookup

Pipeline:
  classify_intent → retrieve_context → enrich_lead → score_lead → route_to_pipeline → END

All LLM calls go through api.llm.llm_router.complete() — never directly to any SDK.
All agent runs are logged to the agent_runs table via helpers in api.agents.graph.
"""

import logging
import re
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from api.agents.graph import build_graph, log_agent_complete, log_agent_start
from api.llm.llm_router import complete
from api.models.crm_models import LeadStage
from api.rag.retriever import query as rag_query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------

class LeadState(TypedDict):
    # ── Inputs (provided at graph entry) ───────────────────────────────────
    company:       str
    contact_name:  str
    contact_email: str
    source:        str
    message:       str
    run_id:        str        # set before ainvoke; propagated through all nodes

    # ── Node outputs (filled as the graph runs) ─────────────────────────────
    intent:        str        # classify_intent  — 1-3 word intent label
    context:       list       # retrieve_context — RAG chunk texts
    enrichment:    dict       # enrich_lead      — structured enrichment dict
    score:         int        # score_lead       — 0-100 quality score
    stage:         str        # route_to_pipeline — LeadStage value string
    reasoning:     str        # route_to_pipeline — human-readable routing rationale


# ---------------------------------------------------------------------------
# Node 1: classify_intent
# ---------------------------------------------------------------------------

async def classify_intent(state: LeadState) -> dict:
    """
    Classify what the lead is asking for in 1–3 words.

    Why this node? Intent is the fastest signal for routing — "pricing inquiry"
    vs "demo request" vs "support question" changes the entire downstream flow.
    We capture it first so every later node can reference it.
    """
    prompt = (
        f"Classify the intent of this lead message in 1 to 3 words only. "
        f"Examples: 'pricing inquiry', 'demo request', 'partnership proposal', 'support question'.\n\n"
        f"Message: {state['message']}\n\n"
        f"Intent (1-3 words only, no explanation):"
    )

    try:
        result = await complete(prompt)
        intent = result.strip().strip('"').strip("'")
        # Truncate to be safe — we never want a paragraph here
        intent = intent[:100] if len(intent) > 100 else intent
    except Exception as exc:
        logger.warning("classify_intent LLM call failed: %s", exc)
        intent = "unknown intent"

    logger.info("classify_intent | run_id=%s | intent=%s", state["run_id"], intent)
    return {"intent": intent}


# ---------------------------------------------------------------------------
# Node 2: retrieve_context
# ---------------------------------------------------------------------------

async def retrieve_context(state: LeadState) -> dict:
    """
    Retrieve product/company context from the RAG knowledge base.

    Why RAG here? The enrichment and scoring nodes need to know what Nexus-AI
    actually offers so they can match it against the lead's needs. Without this,
    scoring is pure guesswork.

    Failure is handled gracefully — an empty context list is valid. The downstream
    nodes will still function; they'll just score based on the message alone.
    """
    try:
        result = await rag_query(q=state["message"], top_k=3)
        chunks = [s["text"] for s in result.sources]
    except Exception as exc:
        logger.warning("retrieve_context RAG call failed: %s", exc)
        chunks = []

    logger.info(
        "retrieve_context | run_id=%s | chunks_retrieved=%d",
        state["run_id"], len(chunks),
    )
    return {"context": chunks}


# ---------------------------------------------------------------------------
# Node 3: enrich_lead
# ---------------------------------------------------------------------------

async def enrich_lead(state: LeadState) -> dict:
    """
    Extract structured enrichment signals from the lead's message.

    We ask the LLM to extract four fields that directly drive scoring:
      - industry: What sector the company operates in
      - company_size_estimate: rough headcount/tier ('startup', 'mid-market', 'enterprise')
      - urgency: How urgently they need a solution ('immediate', 'this quarter', 'exploring')
      - red_flags: Any signals that suggest spam, low intent, or risk

    Why parse rather than strict JSON? LLMs occasionally mis-format JSON under load.
    We do best-effort extraction and fall back to storing the raw string — the scoring
    node can still work with partial enrichment.
    """
    context_text = "\n".join(state["context"]) if state["context"] else "No context available."

    prompt = (
        f"You are analysing an inbound business lead. Extract structured information.\n\n"
        f"Company: {state['company']}\n"
        f"Contact: {state['contact_name']}\n"
        f"Source: {state['source']}\n"
        f"Intent: {state['intent']}\n"
        f"Message: {state['message']}\n\n"
        f"Product context:\n{context_text}\n\n"
        f"Extract these fields (respond as key: value, one per line):\n"
        f"industry: <sector>\n"
        f"company_size_estimate: <startup|mid-market|enterprise>\n"
        f"urgency: <immediate|this_quarter|exploring|unknown>\n"
        f"red_flags: <none, or comma-separated list of red flags>\n\n"
        f"Respond ONLY with the four lines above, no explanation."
    )

    try:
        raw = await complete(prompt)
        enrichment = _parse_key_value(raw)
    except Exception as exc:
        logger.warning("enrich_lead LLM call failed: %s", exc)
        enrichment = {"raw": "enrichment unavailable"}

    logger.info("enrich_lead | run_id=%s | enrichment=%s", state["run_id"], enrichment)
    return {"enrichment": enrichment}


def _parse_key_value(text: str) -> dict:
    """
    Parse a 'key: value' multiline string into a dict.

    Handles LLM quirks: extra spaces, mixed case keys, stray punctuation.
    Falls back to storing raw text under 'raw' if no parseable lines are found.
    """
    result = {}
    for line in text.strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip().lower()] = value.strip()
    return result if result else {"raw": text.strip()}


# ---------------------------------------------------------------------------
# Node 4: score_lead
# ---------------------------------------------------------------------------

async def score_lead(state: LeadState) -> dict:
    """
    Score the lead 0–100 using all accumulated signals.

    Scoring criteria passed to the LLM:
      - High urgency + clear budget signals → higher score
      - Enterprise/mid-market size → higher score
      - Vague message, no contact info → lower score
      - Red flags (spam, irrelevant) → very low score

    We ask for a single integer only. The parsing step extracts the first
    integer it finds in the response — robust against preamble like "Score: 72".
    Default to 50 on any failure so the lead doesn't vanish from the pipeline.
    """
    context_text = "\n".join(state["context"]) if state["context"] else "No context."
    enrichment_text = "\n".join(
        f"{k}: {v}" for k, v in state["enrichment"].items()
    )

    prompt = (
        f"Score this inbound business lead from 0 to 100.\n\n"
        f"Scoring guide:\n"
        f"  90-100: Enterprise, clear budget, immediate urgency, specific ask\n"
        f"  70-89:  Mid-market or enterprise, some urgency, reasonable fit\n"
        f"  50-69:  Exploring, unclear budget, possible fit\n"
        f"  20-49:  Vague, no budget signals, low intent\n"
        f"  0-19:   Spam, off-topic, or obvious red flags\n\n"
        f"Lead details:\n"
        f"  Company: {state['company']}\n"
        f"  Message: {state['message']}\n"
        f"  Intent: {state['intent']}\n"
        f"  Enrichment:\n{enrichment_text}\n\n"
        f"Product context:\n{context_text}\n\n"
        f"Respond with ONLY a single integer between 0 and 100. No text."
    )

    try:
        raw = await complete(prompt)
        score = _extract_integer(raw, default=50)
        score = max(0, min(100, score))  # clamp to valid range
    except Exception as exc:
        logger.warning("score_lead LLM call failed: %s", exc)
        score = 50

    logger.info("score_lead | run_id=%s | score=%d", state["run_id"], score)
    return {"score": score}


def _extract_integer(text: str, default: int = 50) -> int:
    """
    Extract the first integer found in an LLM response string.

    Handles responses like "72", "Score: 72", "I would rate this 72/100".
    Returns `default` if no integer is found.
    """
    match = re.search(r"\b(\d{1,3})\b", text.strip())
    if match:
        return int(match.group(1))
    return default


# ---------------------------------------------------------------------------
# Node 5: route_to_pipeline
# ---------------------------------------------------------------------------

async def route_to_pipeline(state: LeadState) -> dict:
    """
    Apply routing rules to assign the final LeadStage and write reasoning.

    Routing rules (from the project spec):
      - red_flags present in enrichment → escalated  (overrides score)
      - score >= 80                     → hot_lead
      - score 50–79                     → nurture
      - score < 50                      → disqualified

    Why check red_flags first? A score of 90 doesn't mean much if the
    enrichment flagged "payment fraud" or "competitor research". Escalation
    lets a human review edge cases before they enter the pipeline.

    The reasoning string is stored in SQLite and surfaced in the dashboard
    trace view so sales reps understand why a lead was classified a certain way.
    """
    score = state["score"]
    enrichment = state["enrichment"]

    # Check for red flags (case-insensitive, handles missing key gracefully)
    red_flags_raw = str(enrichment.get("red_flags", "none")).lower()
    has_red_flags = red_flags_raw not in ("none", "", "no red flags", "n/a")

    if has_red_flags:
        stage = LeadStage.escalated
        reasoning = (
            f"Escalated due to red flags: '{enrichment.get('red_flags', 'unknown')}'. "
            f"Score was {score}/100 but manual review required."
        )
    elif score >= 80:
        stage = LeadStage.hot_lead
        reasoning = (
            f"Hot lead: score {score}/100 meets the ≥80 threshold. "
            f"Intent '{state['intent']}', urgency '{enrichment.get('urgency', 'unknown')}'. "
            f"Fast-track to sales call."
        )
    elif score >= 50:
        stage = LeadStage.nurture
        reasoning = (
            f"Nurture: score {score}/100 (50–79 range). "
            f"Intent '{state['intent']}', size estimate '{enrichment.get('company_size_estimate', 'unknown')}'. "
            f"Add to drip sequence and follow up in 7 days."
        )
    else:
        stage = LeadStage.disqualified
        reasoning = (
            f"Disqualified: score {score}/100 is below 50. "
            f"Intent '{state['intent']}'. "
            f"Message showed low fit or low intent — remove from active pipeline."
        )

    logger.info(
        "route_to_pipeline | run_id=%s | stage=%s | score=%d",
        state["run_id"], stage.value, score,
    )
    return {"stage": stage.value, "reasoning": reasoning}


# ---------------------------------------------------------------------------
# Compiled graph (module-level singleton — built once on first import)
# ---------------------------------------------------------------------------

# Building the graph once at import time avoids rebuilding it on every request.
# The MemorySaver checkpointer inside build_graph() is per-thread, so concurrent
# requests each get isolated state via their unique thread_id in the config.
_lead_graph = build_graph(
    state_schema=LeadState,
    nodes=[
        ("classify_intent",    classify_intent),
        ("retrieve_context",   retrieve_context),
        ("enrich_lead",        enrich_lead),
        ("score_lead",         score_lead),
        ("route_to_pipeline",  route_to_pipeline),
    ],
    edges=[
        ("classify_intent",   "retrieve_context"),
        ("retrieve_context",  "enrich_lead"),
        ("enrich_lead",       "score_lead"),
        ("score_lead",        "route_to_pipeline"),
        ("route_to_pipeline", END),
    ],
    entry_point="classify_intent",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def classify_lead(
    company: str,
    contact_name: str,
    contact_email: str,
    source: str,
    message: str,
) -> dict:
    """
    Classify an inbound lead through the 5-node LangGraph pipeline.

    Logs start + end to the agent_runs table. On failure, marks the run as
    'failed' rather than leaving it as 'running'.

    Args:
        company:       Company or organisation name.
        contact_name:  Primary contact full name.
        contact_email: Primary contact email (optional — empty string is fine).
        source:        Lead source (website, referral, LinkedIn, etc.).
        message:       The lead's raw message / enquiry.

    Returns:
        dict with keys: stage, score, reasoning, run_id

    Raises:
        Any exception from the graph is re-raised after logging status='failed'.
    """
    run_id = str(uuid4())

    input_data = {
        "company":       company,
        "contact_name":  contact_name,
        "contact_email": contact_email,
        "source":        source,
        "message":       message,
    }

    row_id = await log_agent_start("lead_classifier", run_id, input_data)

    # Build initial state — all node-output fields start empty/zero
    initial_state: LeadState = {
        "company":       company,
        "contact_name":  contact_name,
        "contact_email": contact_email,
        "source":        source,
        "message":       message,
        "run_id":        run_id,
        # Node outputs — populated as graph runs
        "intent":     "",
        "context":    [],
        "enrichment": {},
        "score":      0,
        "stage":      "",
        "reasoning":  "",
    }

    try:
        result = await _lead_graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": run_id}},
        )

        output = {
            "stage":     result["stage"],
            "score":     result["score"],
            "reasoning": result["reasoning"],
            "run_id":    run_id,
        }

        await log_agent_complete(row_id, output, status="completed")
        logger.info(
            "classify_lead complete | run_id=%s | stage=%s | score=%d",
            run_id, output["stage"], output["score"],
        )
        return output

    except Exception as exc:
        logger.exception("classify_lead failed | run_id=%s | error=%s", run_id, exc)
        await log_agent_complete(row_id, {"error": str(exc)}, status="failed")
        raise