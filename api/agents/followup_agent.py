"""
api/agents/followup_agent.py
============================
Follow-up Writer Agent for Nexus-AI.

A 5-node LangGraph StateGraph that:
  1. Loads a deal's full history from SQLite (deal + joined lead data)
  2. Retrieves product context from the RAG knowledge base
  3. Drafts a personalised follow-up email
  4. Self-reviews the draft against quality criteria (0–100 score)
  5. Routes: accept if review_score >= 70, loop back to draft_email if < 70 (max 2 retries)

The self-review loop is the key pattern here. Instead of sending the first draft,
the agent critiques its own output and rewrites if the score is too low. This
consistently produces better emails than a single-pass approach — the reviewer
prompt catches missing personalisation, vague CTAs, and off-topic content that
the drafting prompt often slips through on the first attempt.

Pipeline:
  load_deal_history → retrieve_product_context → draft_email → self_review
                                                      ↑              ↓
                                                (loop back)   route_by_confidence
                                                                     ↓
                                                                    END

All LLM calls go through api.llm.llm_router.complete() — never directly to any SDK.
All agent runs are logged to the agent_runs table via helpers in api.agents.graph.
"""

import logging
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from api.agents.graph import log_agent_complete, log_agent_start
from api.database import get_db
from api.llm.llm_router import complete
from api.rag.retriever import query as rag_query

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------

class FollowupState(TypedDict):
    # ── Inputs (provided at graph entry) ───────────────────────────────────
    deal_id:      str
    run_id:       str

    # ── Node outputs (filled as the graph runs) ─────────────────────────────
    deal_history:  dict       # load_deal_history  — deal + lead data as flat dict
    context:       list       # retrieve_product_context — RAG chunk texts
    draft:         str        # draft_email        — the email text
    review_score:  int        # self_review        — 0-100 quality score
    review_notes:  str        # self_review        — what to improve (fed back to draft_email)
    retry_count:   int        # tracks how many times we've looped back to draft_email


# ---------------------------------------------------------------------------
# Node 1: load_deal_history
# ---------------------------------------------------------------------------

async def load_deal_history(state: FollowupState) -> dict:
    """
    Load the deal and its parent lead from SQLite as a single flat dict.

    Why JOIN here instead of two queries? A follow-up email needs both deal
    context (stage, value, last contact) AND lead context (company, contact name,
    email) in every downstream node. One JOIN is simpler and faster than passing
    two separate objects through the state.

    Raises ValueError if the deal_id doesn't exist — this propagates up to
    write_followup() which logs it as status='failed'.
    """
    deal_id = state["deal_id"]

    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT
                d.id          AS deal_id,
                d.stage       AS deal_stage,
                d.value       AS deal_value,
                d.owner       AS deal_owner,
                d.last_contact,
                d.created_at  AS deal_created_at,
                l.id          AS lead_id,
                l.company,
                l.contact_name,
                l.contact_email,
                l.source,
                l.stage       AS lead_stage,
                l.score       AS lead_score
            FROM deals d
            JOIN leads l ON d.lead_id = l.id
            WHERE d.id = ?
            """,
            (deal_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise ValueError(f"Deal {deal_id} not found in the database.")

    deal_history = dict(row)
    logger.info(
        "load_deal_history | run_id=%s | company=%s | stage=%s",
        state["run_id"], deal_history.get("company"), deal_history.get("deal_stage"),
    )
    return {"deal_history": deal_history}


# ---------------------------------------------------------------------------
# Node 2: retrieve_product_context
# ---------------------------------------------------------------------------

async def retrieve_product_context(state: FollowupState) -> dict:
    """
    Retrieve product/company context from the RAG knowledge base.

    Builds a query from the deal's company name and stage so the chunks
    retrieved are relevant to this specific deal type. A 'proposal' stage
    deal needs different context than a 'nurture' stage deal.

    Failure is handled gracefully — an empty context list is valid.
    The draft_email node will still produce a reasonable email; it just
    won't reference specific product features from the knowledge base.
    """
    dh = state["deal_history"]
    q = f"{dh.get('company', '')} {dh.get('deal_stage', '')} CRM solution follow-up"

    try:
        result = await rag_query(q=q, top_k=3)
        chunks = [s["text"] for s in result.sources]
    except Exception as exc:
        logger.warning("retrieve_product_context RAG call failed: %s", exc)
        chunks = []

    logger.info(
        "retrieve_product_context | run_id=%s | chunks_retrieved=%d",
        state["run_id"], len(chunks),
    )
    return {"context": chunks}


# ---------------------------------------------------------------------------
# Node 3: draft_email
# ---------------------------------------------------------------------------

async def draft_email(state: FollowupState) -> dict:
    """
    Draft a personalised follow-up email using deal history and RAG context.

    On the first attempt, review_notes is an empty string — the prompt just
    asks for a good first draft. On retry attempts, review_notes contains the
    self-reviewer's critique from the previous round. This feedback loop is
    what makes the self-review pattern effective: the drafter sees exactly
    what was wrong and can correct it.

    Key constraints baked into the prompt:
      - Reference the specific company and contact by name (personalisation)
      - Reference a fact from the deal history (shows attention to context)
      - Under 200 words (respects the recipient's time)
      - Clear call to action (moves the deal forward)
      - No placeholder text like [Your Name] or [Date] (production-ready)
    """
    dh = state["deal_history"]
    context_text = "\n".join(state["context"]) if state["context"] else "No product context available."
    review_notes = state.get("review_notes", "")
    retry_count  = state.get("retry_count", 0)

    # Build the feedback section — only shown on retry attempts
    feedback_section = ""
    if review_notes and retry_count > 0:
        feedback_section = (
            f"\n\nPREVIOUS DRAFT FEEDBACK (address all points):\n{review_notes}"
        )

    prompt = (
        f"Write a professional follow-up email for a business deal.\n\n"
        f"Deal details:\n"
        f"  Company:       {dh.get('company', 'Unknown')}\n"
        f"  Contact:       {dh.get('contact_name', 'Unknown')}\n"
        f"  Deal stage:    {dh.get('deal_stage', 'Unknown')}\n"
        f"  Deal value:    ${dh.get('deal_value') or 'TBD'}\n"
        f"  Last contact:  {dh.get('last_contact') or 'Not recorded'}\n"
        f"  Lead source:   {dh.get('source', 'Unknown')}\n\n"
        f"Product context (reference at least one relevant fact):\n{context_text}\n"
        f"{feedback_section}\n\n"
        f"Requirements:\n"
        f"  - Address {dh.get('contact_name', 'the contact')} by name\n"
        f"  - Reference the company {dh.get('company', '')} specifically\n"
        f"  - Under 200 words\n"
        f"  - One clear call to action (suggest a specific next step)\n"
        f"  - No placeholder text\n"
        f"  - Professional but warm tone\n\n"
        f"Write only the email body (no subject line, no metadata):"
    )

    try:
        draft = await complete(prompt)
        draft = draft.strip()
    except Exception as exc:
        logger.warning("draft_email LLM call failed: %s", exc)
        draft = (
            f"Hi {dh.get('contact_name', 'there')},\n\n"
            f"I wanted to follow up on our conversation about {dh.get('company', 'your company')}. "
            f"Would you be available for a brief call this week?\n\n"
            f"Best regards"
        )

    # Increment retry_count here — draft_email is the node that loops back,
    # so it owns the counter. route_by_confidence is a conditional EDGE function
    # (not a node) and cannot return state updates in LangGraph — mutations to
    # state inside an edge function are silently ignored. The only way to persist
    # the incremented count across the loop is to return it from the node itself.
    new_retry_count = retry_count + 1

    logger.info(
        "draft_email | run_id=%s | retry=%d | draft_len=%d",
        state["run_id"], retry_count, len(draft),
    )
    return {"draft": draft, "retry_count": new_retry_count}


# ---------------------------------------------------------------------------
# Node 4: self_review
# ---------------------------------------------------------------------------

async def self_review(state: FollowupState) -> dict:
    """
    Self-review the drafted email against quality criteria.

    Why self-review? A single LLM call produces variable quality. Adding a
    second LLM call that explicitly evaluates the first output catches common
    failures: generic openers, missing personalisation, weak CTAs, excessive
    length. The reviewer prompt is more constrained than the drafter prompt,
    which makes the critique reliable.

    The SCORE/NOTES format is deliberately rigid — we need to parse it
    programmatically. If parsing fails we default to 70 (just above the
    retry threshold) so the agent doesn't loop forever on a parse error.

    Scoring rubric sent to the LLM:
      90-100: Personalised, specific, concise, compelling CTA
      70-89:  Good but minor improvements possible
      50-69:  Generic or missing key elements — needs rewrite
      0-49:   Major problems — no personalisation, placeholder text, off-topic
    """
    dh    = state["deal_history"]
    draft = state["draft"]

    prompt = (
        f"Review this follow-up email and score it 0-100.\n\n"
        f"EMAIL:\n{draft}\n\n"
        f"DEAL CONTEXT:\n"
        f"  Company: {dh.get('company')}\n"
        f"  Contact: {dh.get('contact_name')}\n"
        f"  Stage:   {dh.get('deal_stage')}\n\n"
        f"Scoring criteria:\n"
        f"  - Is the contact addressed by name? (+20)\n"
        f"  - Is the company referenced specifically? (+20)\n"
        f"  - Is there a clear, specific call to action? (+20)\n"
        f"  - Is it under 200 words? (+20)\n"
        f"  - Is there zero placeholder text? (+20)\n\n"
        f"Respond in EXACTLY this format (two lines only):\n"
        f"SCORE: <integer 0-100>\n"
        f"NOTES: <one sentence describing the most important improvement, or 'None' if perfect>"
    )

    try:
        raw = await complete(prompt)
        review_score, review_notes = _parse_review(raw)
    except Exception as exc:
        logger.warning("self_review LLM call failed: %s", exc)
        review_score = 70   # default above threshold — don't loop on LLM failure
        review_notes = "Review unavailable."

    logger.info(
        "self_review | run_id=%s | retry=%d | score=%d",
        state["run_id"], state.get("retry_count", 0), review_score,
    )
    return {"review_score": review_score, "review_notes": review_notes}


def _parse_review(text: str) -> tuple[int, str]:
    """
    Parse the self-review response into (score, notes).

    Expected format:
        SCORE: 78
        NOTES: Add a specific call to action with a suggested meeting time.

    Tolerant of extra whitespace, lowercase labels, and stray text.
    Returns (70, "Parse failed") if the format is not found — safe default.
    """
    import re
    score = 70
    notes = "No notes provided."

    score_match = re.search(r"SCORE\s*:\s*(\d{1,3})", text, re.IGNORECASE)
    notes_match = re.search(r"NOTES\s*:\s*(.+)", text, re.IGNORECASE)

    if score_match:
        score = max(0, min(100, int(score_match.group(1))))
    if notes_match:
        notes = notes_match.group(1).strip()

    return score, notes


# ---------------------------------------------------------------------------
# Conditional edge: route_by_confidence
# ---------------------------------------------------------------------------

def route_by_confidence(state: FollowupState) -> str:
    """
    Decide what happens after self_review.

    This is a conditional edge function — it returns a string key that
    LangGraph uses to pick the next node.

    Logic:
      - review_score >= 70: draft is good enough → END
      - review_score < 70 AND retry_count < 2: loop back to draft_email
        (the review_notes from self_review will be fed into the next draft)
      - retry_count >= 2: accept best effort regardless of score → END
        (prevents infinite loops on hard leads or unreliable LLM responses)

    Why 70 as the threshold? It's the point where all core criteria are met
    (personalised, specific, has CTA, under 200 words). Below 70 means at
    least one criterion is clearly missing. Above 70 means the email is
    send-ready even if not perfect.

    Why max 2 retries? Each retry costs 2 LLM calls (~4-8 seconds). Three
    total attempts (original + 2 retries) gives the agent enough chances to
    improve without making the API endpoint unacceptably slow.
    """
    score       = state.get("review_score", 0)
    retry_count = state.get("retry_count", 0)

    if score >= 70:
        logger.info(
            "route_by_confidence | run_id=%s | score=%d ≥ 70 → END",
            state["run_id"], score,
        )
        return "END"

    if retry_count < 2:
        logger.info(
            "route_by_confidence | run_id=%s | score=%d < 70 | retry=%d → draft_email",
            state["run_id"], score, retry_count,
        )
        # retry_count is incremented by draft_email node on re-entry —
        # edge functions cannot update state in LangGraph.
        return "draft_email"

    # retry_count >= 2 — accept best effort
    logger.info(
        "route_by_confidence | run_id=%s | score=%d | max retries reached → END",
        state["run_id"], score,
    )
    return "END"


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------
# The follow-up graph can't use build_graph() from graph.py because it needs
# a conditional edge (self_review → draft_email loop). We wire it manually
# using StateGraph directly, which is what build_graph() wraps anyway.

def _build_followup_graph():
    from langgraph.checkpoint.memory import MemorySaver

    builder = StateGraph(FollowupState)

    # Register nodes
    builder.add_node("load_deal_history",         load_deal_history)
    builder.add_node("retrieve_product_context",  retrieve_product_context)
    builder.add_node("draft_email",               draft_email)
    builder.add_node("self_review",               self_review)

    # Linear edges up to self_review
    builder.set_entry_point("load_deal_history")
    builder.add_edge("load_deal_history",        "retrieve_product_context")
    builder.add_edge("retrieve_product_context", "draft_email")
    builder.add_edge("draft_email",              "self_review")

    # Conditional edge: self_review → draft_email (retry) or END (accept)
    builder.add_conditional_edges(
        "self_review",
        route_by_confidence,
        {
            "draft_email": "draft_email",   # loop back
            "END":         END,             # accept draft
        },
    )

    return builder.compile(checkpointer=MemorySaver())


# Module-level singleton — built once at import, reused per request
_followup_graph = _build_followup_graph()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def write_followup(deal_id: str) -> dict:
    """
    Write a follow-up email for the given deal through the self-review pipeline.

    Logs start + end to the agent_runs table. On failure, marks the run as
    'failed' rather than leaving it as 'running'.

    Args:
        deal_id: The UUID of the deal row in the deals table.
                 Use the seed script to insert a test deal if needed.

    Returns:
        dict with keys: draft, review_score, run_id

    Raises:
        ValueError: If the deal_id is not found (propagated from load_deal_history).
        Any other exception from the graph is re-raised after logging status='failed'.
    """
    run_id = str(uuid4())

    input_data = {"deal_id": deal_id}
    row_id = await log_agent_start("followup_writer", run_id, input_data)

    # Build initial state — all node-output fields start empty/zero
    initial_state: FollowupState = {
        "deal_id":      deal_id,
        "run_id":       run_id,
        "deal_history": {},
        "context":      [],
        "draft":        "",
        "review_score": 0,
        "review_notes": "",
        "retry_count":  0,
    }

    try:
        result = await _followup_graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": run_id}},
        )

        output = {
            "draft":        result["draft"],
            "review_score": result["review_score"],
            "run_id":       run_id,
        }

        await log_agent_complete(row_id, output, status="completed")
        logger.info(
            "write_followup complete | run_id=%s | review_score=%d | retries=%d",
            run_id, result["review_score"], result.get("retry_count", 0),
        )
        return output

    except Exception as exc:
        logger.exception("write_followup failed | run_id=%s | error=%s", run_id, exc)
        await log_agent_complete(row_id, {"error": str(exc)}, status="failed")
        raise