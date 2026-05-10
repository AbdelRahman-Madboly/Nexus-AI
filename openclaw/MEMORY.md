# MEMORY.md — Company Context Seed
# =====================================================================
# This file seeds Nexus with the company and product context it needs
# to give accurate, relevant answers from day one.
#
# Loaded alongside SOUL.md as background knowledge.
# This is NOT the knowledge base (ChromaDB) — it is the assistant's
# built-in memory of who it works for and how the business operates.
# =====================================================================

---

## The Company

**Name:** Projecx
**Website:** projecx.io
**HQ:** Abu Dhabi, United Arab Emirates
**Type:** Business Development Studio — builds and operates AI-powered SaaS products.
**Contact:** info@projecx.io · Abdallah Zaqout (LinkedIn)

---

## Products

### Revenyu CRM
- AI-first CRM platform for sales teams.
- Core differentiator: AI agent layer built on Llama 3 — not a bolt-on chatbot, but agents embedded in the workflow.
- Target customer: mid-market companies (50–500 person sales orgs) wanting to replace legacy CRMs.
- Key feature: AI-assisted lead scoring, follow-up drafting, and pipeline analytics.

### Bandora CMS
- AI Content Intelligence platform.
- Helps marketing teams generate, review, and publish content faster.
- Core differentiator: AI editorial layer that understands brand voice and content strategy.
- Target customer: marketing teams at mid-market B2B companies.

---

## Target Customers

- Mid-market companies wanting AI-first business operations.
- Industries: real estate, fintech, professional services, SaaS.
- Decision-maker profile: Sales Director, VP of Sales, COO — values data over gut feel.
- Deal size: typically 6-figure ACV for enterprise deployment.

---

## The Sales Pipeline — Stage Definitions

Nexus uses these exact stage names in the CRM. Nexus must use them as-is — never invent new stages.

| Stage | Meaning | Score threshold |
|---|---|---|
| `new_lead` | Just entered the system, not yet scored | — |
| `hot_lead` | High-intent, qualified, ready for immediate follow-up | score ≥ 80 |
| `nurture` | Interested but not ready — needs education and time | score 50–79 |
| `proposal` | Actively in negotiation, proposal sent | — |
| `closed_won` | Deal signed | — |
| `closed_lost` | Deal lost | — |
| `disqualified` | Not a fit — wrong size, wrong budget, wrong timing | score < 50 |
| `escalated` | Red flags present (competitor mention, unrealistic timeline, legal risk) | overrides score |

---

## KPI Thresholds the Team Tracks

| KPI | Target / Warning level |
|---|---|
| Hot lead threshold | Score ≥ 80 |
| Conversion rate target | > 30% (closed_won / all closed) |
| Deal age warning | > 30 days in pipeline without movement |
| Stage overload warning | Any single stage > 40% of total leads |
| Lead qualification bottleneck | new_lead count > (hot_lead + nurture) combined |

When reporting KPIs, always compare against these thresholds — say whether each metric is on target, at risk, or in warning territory.

---

## Team Context

- Small, fast-moving team. Decision velocity matters.
- Values data over gut feel — back every recommendation with a number.
- Prefers short, actionable responses over lengthy explanations.
- Common requests via Nexus: "How many hot leads?", "Draft a follow-up for deal X", "What is Revenyu?", "Pipeline report".

---

## Technical Context (for Nexus's own awareness)

- Nexus runs on the Nexus-AI platform (self-hosted, privacy-first).
- LLM backend is switchable: currently Gemini 2.5 Flash (cloud) or Ollama gemma3:4b (local).
- PRIVACY_MODE=true forces all LLM calls to local Ollama — no data leaves the machine.
- Knowledge base is ChromaDB, hybrid semantic + BM25 retrieval.
- Agents are LangGraph StateGraphs — each lead classification and follow-up draft is a logged, traceable run.

---

*MEMORY.md — Company Context Seed*
*Version: 1.0 | Phase 4*
*Owner: Abdel Rahman M. El-Saied*