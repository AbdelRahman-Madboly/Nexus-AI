# Nexus-AI — System Architecture
> Version: 1.0.0 | Date: May 11, 2026
> Owner: Abdel Rahman M. El-Saied

---

## Section 1: Overview

Nexus-AI is a production-quality, fully self-hosted AI business operations platform. It brings AI into the full lifecycle of a B2B sales pipeline by combining a RAG knowledge engine, multi-agent CRM automation, a messaging gateway, workflow automation, and a React dashboard — all wired together behind a single FastAPI backend and deployable with one command. The platform was built specifically to demonstrate alignment with the AI engineering vision of Projecx (projecx.io), a company building AI-powered SaaS products (Revenyu CRM, Bandora CMS) on a confirmed stack of Python, FastAPI, Ollama, React, n8n, LangGraph, and ChromaDB.

Privacy is a first-class design constraint. Set `PRIVACY_MODE=true` in `.env` and every single LLM call routes to your local Ollama instance — no data leaves the machine. Embeddings are always local (Ollama `nomic-embed-text`) regardless of which LLM backend is selected, so ChromaDB vectors remain consistent across ingest and query sessions. Switching LLM providers requires a single environment variable change and zero code changes.

---

## Section 2: Architecture Diagram

```
                    ┌──────────────────────────────────────────────────────┐
                    │                  Nexus-AI Platform                    │
                    │                                                       │
  Browser ─────────►  React Dashboard         (port 3000)                  │
                    │  Vite · React 18 · TypeScript · TailwindCSS          │
                    │  RagChat · AgentTracer · Pipeline Kanban              │
                    │                         │                            │
                    │                         ▼                            │
  Claude  ──MCP/SSE►  FastAPI Gateway         (port 8000)                  │
  Desktop           │  ├── RAG Engine ──────────────────► ChromaDB (8001)  │
                    │  │   Ingestor: PDF/DOCX/MD/URL                      │
                    │  │   Retriever: Semantic + BM25                     │
                    │  │   Reranker: CrossEncoder ms-marco                │
                    │  │                                                   │
                    │  ├── LangGraph Agents ──────────────► SQLite (nexus.db)│
                    │  │   Lead Classifier   (5 nodes)                    │
                    │  │   Follow-up Writer  (5 nodes + self-review)      │
                    │  │   Pipeline Reporter (5 nodes, 4 KPI sections)    │
                    │  │                                                   │
                    │  └── MCP Server (FastMCP, 10 tools, SSE /mcp/sse)   │
                    │                                                       │
  Telegram ─────────►  OpenClaw Gateway       (port 3456)                  │
  WhatsApp          │  Intent Router: pipeline | leads | rag               │
  Slack    ◄────────►  Skills: nexus-rag · nexus-leads · nexus-pipeline    │
                    │                                                       │
  Webhooks ─────────►  n8n Automation         (port 5678)                  │
                    │  lead-intake · followup-scheduler                    │
                    │  pipeline-digest · alert-escalation                  │
                    │                                                       │
                    │  LLM Router ─────────────────────────────────────────►  Ollama (Windows host, RTX 4050)
                    │  openai | claude | gemini | ollama                   │  gemma3:4b · nomic-embed-text
                    │  PRIVACY_MODE=true → always Ollama                   │
                    └──────────────────────────────────────────────────────┘
```

---

## Section 3: Component Table

| Component | Technology | Port | Purpose |
|---|---|---|---|
| `nexus-api` | FastAPI · Python 3.12 · uvicorn | 8000 | Central AI backend — RAG, agents, MCP, routing |
| `nexus-chroma` | ChromaDB 0.6.3 | 8001 (host) / 8000 (internal) | Vector store for RAG document embeddings |
| `nexus-ollama` | Ollama (container, empty) | 11434 | Placeholder; all model calls go to Windows Ollama via host IP |
| `nexus-n8n` | n8n (latest) | 5678 | Workflow automation — 4 JSON workflows |
| `nexus-ui` | Vite + React 18 (two-stage Docker build) | 3000 | React dashboard — RagChat, AgentTracer, Pipeline |
| `nexus-openclaw` | Node.js 22 | 3456 | Messaging gateway — Telegram, WhatsApp, Slack |
| Ollama (Windows host) | Ollama · RTX 4050 · CUDA 8.9 | 11434 | LLM inference + embeddings (`gemma3:4b`, `nomic-embed-text`) |
| SQLite (`nexus.db`) | aiosqlite · WAL mode | file | Persistent store — leads, deals, agent_runs, rag_queries |

---

## Section 4: Data Flow — Lead Intelligence

What happens from "lead arrives" to "classified and Slack notified":

1. **Lead arrives** — via any channel: `POST /api/agents/lead/classify` (API/dashboard), `classify lead ...` message (Telegram/WhatsApp/Slack via OpenClaw), or `POST http://localhost:5678/webhook/lead-intake` (n8n webhook from web form or CRM).

2. **OpenClaw intent routing (if messaging channel)** — `routeIntent()` scans the message for keywords. "classify" or "lead" → `nexus-leads` skill. The skill POSTs to `http://nexus-api:8000/api/agents/lead/classify` with extracted fields.

3. **n8n webhook (if automation channel)** — the Lead Intake workflow extracts fields from the webhook payload and POSTs to `http://nexus-api:8000/api/agents/lead/classify` with a 60s timeout.

4. **Agent run logged** — `agent_router.py` creates an `agent_runs` record in SQLite with status `running` and the full input JSON. A `run_id` (UUID) is assigned.

5. **Node 1 — `classify_intent`** — LangGraph calls `llm_router.complete()` with the lead message. The LLM (via the configured backend) returns an intent string: e.g. `"high_value_enterprise"`.

6. **Node 2 — `retrieve_context`** — the agent calls `retriever.query()` to fetch relevant chunks from ChromaDB using the lead's company name and message. Context enriches subsequent nodes.

7. **Node 3 — `enrich_lead`** — LLM synthesises a structured enrichment dict from the intent, message, and retrieved context: industry, urgency signals, decision-maker indicators.

8. **Node 4 — `score_lead`** — LLM outputs a score (0–100) with reasoning. Scoring rules: signals like "C-level approval", "budget confirmed", "specific timeline" push score toward 90+.

9. **Node 5 — `route_to_pipeline`** — conditional edge: `score >= 80` → `hot_lead`; `50–79` → `nurture`; `< 50` → `disqualified`; red flags present → `escalated`. Lead record written to SQLite `leads` table.

10. **Agent run completed** — `agent_runs` record updated to `completed` with full output JSON. API returns `{ stage, score, reasoning, run_id }`.

11. **Notification** — if triggered via n8n: the IF node checks `stage == hot_lead OR escalated`, posts to `#sales-alerts` (Slack), or `#sales-leads`. If triggered via OpenClaw: the skill formats the response with emoji and stage badge and sends it back to the originating channel.

---

## Section 5: Data Flow — RAG Query

What happens from "user asks a question" to "cited answer appears in the dashboard":

1. **Query received** — `POST /api/rag/query` with `{ query, top_k, stream }`. The `rag_router.py` calls `retriever.query()`.

2. **Parallel retrieval** — two searches run concurrently via `asyncio.gather`:
   - **Semantic search**: `llm_router.embed(query)` → 768-dim vector via Ollama `nomic-embed-text` → ChromaDB `query()` returns top 10 nearest chunks.
   - **BM25 search**: `_chroma_get_all()` fetches the full corpus (one round-trip, reused) → `BM25Okapi` scores all documents → top 10 keyword matches.

3. **Hybrid merge** — results deduplicated by chunk ID. Where both methods returned the same chunk, semantic score wins. Combined candidate set passed to reranker.

4. **CrossEncoder reranking** — `cross-encoder/ms-marco-MiniLM-L-6-v2` (run in `executor` to avoid blocking the async loop) scores each candidate against the original query. Top `top_k` chunks selected (default 3).

5. **LLM answer generation** — system prompt instructs the LLM to answer only from provided context and cite sources `[1]`, `[2]`, `[3]`. `llm_router.complete()` routes to the configured backend. Answer streamed or returned as string.

6. **Logging** — query, answer, sources, latency, and model used written to `rag_queries` table in SQLite. Failure to log never breaks the response.

7. **Response returned** — `{ answer, sources: [{id, text, metadata, score}], latency_ms }`. Dashboard `RagChat.tsx` renders the answer in the left panel and source citation chips in the right panel (72-char excerpts, score badges).

---

## Section 6: LLM Backend

All LLM calls in the entire project go through a single file: `api/llm/llm_router.py`. Feature code never imports an LLM SDK directly — this is an absolute engineering rule enforced by code review.

### Routing logic

```
complete(prompt, system_prompt=None)
  → get_settings().effective_llm_backend
      PRIVACY_MODE=true  → always "ollama" (regardless of LLM_BACKEND)
      PRIVACY_MODE=false → value of LLM_BACKEND from .env
  → lazy-import the correct client → call complete() → return string

embed(text)
  → always ollama_client.embed()
  (hardwired — never routed. Mixing providers corrupts ChromaDB vector space.)
```

### Switching backends

Change one variable in `.env`. Zero code changes required.

```bash
# Gemini (default — fast, generous free tier)
LLM_BACKEND=gemini
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-2.5-flash

# Claude
LLM_BACKEND=claude
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-5

# OpenAI
LLM_BACKEND=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# Fully private — no external API calls
LLM_BACKEND=ollama
OLLAMA_BASE_URL=http://172.29.208.1:11434
OLLAMA_MODEL=gemma3:4b
PRIVACY_MODE=true
```

### PRIVACY_MODE

When `PRIVACY_MODE=true`, `config.py` overrides `effective_llm_backend` to always return `"ollama"`. This is enforced at the config layer — no SDK imports, no conditional checks in feature code. The setting is checked on every call, so toggling it in `.env` and restarting the server takes effect immediately.

---

## Section 7: Database Schema

SQLite, WAL mode, async via `aiosqlite`. Four tables:

```sql
-- Inbound leads from all channels
CREATE TABLE leads (
  id            TEXT PRIMARY KEY,
  company       TEXT NOT NULL,
  contact_name  TEXT,
  contact_email TEXT,
  source        TEXT,
  stage         TEXT DEFAULT 'new_lead',   -- LeadStage enum
  score         INTEGER DEFAULT 0,          -- 0–100
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Deals linked to leads; tracks pipeline progression
CREATE TABLE deals (
  id            TEXT PRIMARY KEY,
  lead_id       TEXT REFERENCES leads(id),
  stage         TEXT NOT NULL,
  value         REAL,
  owner         TEXT,
  last_contact  TIMESTAMP,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Every LangGraph agent run — input, output, timing, status
CREATE TABLE agent_runs (
  id           TEXT PRIMARY KEY,
  agent_name   TEXT NOT NULL,
  run_id       TEXT UNIQUE NOT NULL,
  input_json   TEXT,
  output_json  TEXT,
  status       TEXT DEFAULT 'running',   -- running | completed | failed
  started_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP
);

-- Every RAG query — text, answer, sources, latency, model
CREATE TABLE rag_queries (
  id            TEXT PRIMARY KEY,
  query_text    TEXT NOT NULL,
  response_text TEXT,
  sources_json  TEXT,
  latency_ms    INTEGER,
  model_used    TEXT,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**LeadStage values:** `new_lead` · `hot_lead` (score ≥ 80) · `nurture` (50–79) · `proposal` · `closed_won` · `closed_lost` · `disqualified` (< 50) · `escalated` (red flags present)

---

## Section 8: Deployment

### Prerequisites

- WSL2 (Ubuntu 24) with Docker and `docker-compose` (hyphen version) installed
- Ollama running on Windows host with a GPU (RTX 4050 used in development)
  - Required models: `ollama pull nomic-embed-text` and `ollama pull gemma3:4b` (or preferred chat model)
- At least one of: Gemini API key / Anthropic API key / OpenAI API key — or use Ollama only
- Node.js v22+ in WSL (for OpenClaw development; not needed for Docker-only deployment)

### From scratch on a new machine

```bash
# 1. Clone
git clone https://github.com/AbdelRahman-Madboly/Nexus-AI.git
cd Nexus-AI

# 2. Configure
cp .env.example .env
# Edit .env:
#   OLLAMA_BASE_URL=http://<windows-host-ip>:11434
#   LLM_BACKEND=gemini (or ollama for fully private)
#   GEMINI_API_KEY=your-key (if using gemini)

# 3. Start Ollama on Windows host
#    CMD: set OLLAMA_HOST=0.0.0.0 && ollama serve

# 4. Start all 6 services
docker-compose up -d

# 5. Wait 30 seconds (ChromaDB and CrossEncoder initialise)
docker-compose ps          # all 6 should show Up
curl http://localhost:8000/api/health

# 6. Ingest your first document
curl -X POST http://localhost:8000/api/rag/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "https://your-docs-url.com"}'

# 7. Open the dashboard
#    http://localhost:3000
```

### Getting the Windows host IP (WSL2)

The IP changes on reboot. Get the current value with:

```bash
ip route | grep default | awk '{print $3}'
```

Update `OLLAMA_BASE_URL` in `.env` to match.

### Important Docker quirks

- Use `docker-compose` (hyphen) — Compose v2 plugin not installed
- Always `docker-compose down && docker-compose up -d` — never target a single service
- ChromaDB port: `8001` on host, `8000` inside Docker network (use `8000` in env vars)
- After `docker-compose down -v` (data wipe): re-ingest documents before querying
- CrossEncoder model (~90MB) downloads on first startup — expect 3-5 min wait once

For full troubleshooting reference see `DOCKER_REFERENCE.md`.

---

*Nexus-AI Architecture Reference — v1.0.0*
*Owner: Abdel Rahman M. El-Saied*
*GitHub: github.com/AbdelRahman-Madboly/Nexus-AI*