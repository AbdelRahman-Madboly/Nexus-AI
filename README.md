# Nexus-AI

**Self-hosted AI business operations platform — RAG · LangGraph Agents · MCP · Messaging · Automation · Dashboard**

> Deploy with one command. Switch LLM backends with one env variable. Run entirely on local hardware.

<p align="center">
  <img src="docs/images/banner.png" alt="Nexus-AI Banner" width="100%"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-blue?logo=python" />
  <img src="https://img.shields.io/badge/FastAPI-0.136-green?logo=fastapi" />
  <img src="https://img.shields.io/badge/LangGraph-1.1-orange" />
  <img src="https://img.shields.io/badge/React-18-61DAFB?logo=react" />
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker" />
  <img src="https://img.shields.io/badge/Tests-35%2F35%20passing-brightgreen" />
  <img src="https://img.shields.io/badge/License-MIT-lightgrey" />
</p>

---

## What Is Nexus-AI

Nexus-AI is a production-quality, fully self-hosted platform that brings AI into the full lifecycle of a B2B sales pipeline. It combines a RAG knowledge engine, multi-agent CRM automation, a messaging gateway, workflow automation, and a React dashboard — all wired together behind a single FastAPI backend and deployable with `docker-compose up`.

The platform is designed to be privacy-first: set `PRIVACY_MODE=true` and every LLM call routes to your local Ollama instance — no data leaves your machine.

<p align="center">
  <img src="docs/images/architecture.png" alt="Nexus-AI Architecture" width="90%"/>
</p>

---

## Key Features

| Component | What it does |
|---|---|
| **RAG Engine** | Ingest any PDF, DOCX, Markdown, or URL. Query with grounded, cited answers using hybrid semantic + BM25 retrieval and cross-encoder reranking. |
| **Lead Classifier Agent** | Submit a lead and get a classification (hot / nurture / disqualified / escalated), a 0–100 score, and full reasoning — in under 3 seconds. |
| **Follow-up Writer Agent** | Give it a deal ID and get a personalized follow-up email grounded in deal history. Self-reviews its own draft and retries if quality is below threshold. |
| **Pipeline Reporter Agent** | On demand: conversion rate, average deal age, stage distribution, bottleneck analysis, and an LLM-written executive digest. |
| **MCP Server** | 10 tools exposed via FastMCP + SSE. Claude Desktop can query live SQLite data — "How many hot leads?" answered in real time. |
| **OpenClaw Gateway** | Send "classify this lead" via Telegram, WhatsApp, or Slack. The agent classifies it and replies — no dashboard needed. |
| **n8n Automation** | 4 business workflows: lead intake, stale-deal follow-up scheduling, Monday pipeline digest, and alert escalation. |
| **React Dashboard** | RAG chat with streaming and source citations, LangGraph agent trace visualizer, and pipeline Kanban board. |

---

## Architecture

```
FastAPI Gateway (port 8000)
├── RAG Engine
│   ├── Document Ingestor  — PDF/MD/DOCX/URL → chunk → embed → ChromaDB
│   └── Hybrid Retriever   — semantic + BM25 → cross-encoder rerank → LLM → stream
├── LangGraph Agents (SQLite checkpointer)
│   ├── Lead Classifier    — 5 nodes, score-based routing
│   ├── Follow-up Writer   — 5 nodes, self-review loop (max 2 retries, threshold 70)
│   └── Pipeline Reporter  — 5 nodes, 4 KPI sections, rule-based bottleneck detection
├── MCP Server (FastMCP)   — 10 tools, SSE transport, Claude Desktop integration
├── OpenClaw Gateway (port 3456)
│   ├── Skills: nexus-rag · nexus-leads · nexus-pipeline
│   └── Channels: Telegram · WhatsApp · Slack
├── n8n Automation (port 5678)
│   └── 4 workflows: lead-intake · followup-scheduler · pipeline-digest · alert-escalation
├── React Dashboard (port 3000)
│   └── RagChat · AgentTracer · Pipeline Kanban
└── LLM Router
    └── openai | claude | gemini | ollama  (PRIVACY_MODE=true → always Ollama)
```

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [Ollama](https://ollama.com) running locally (required for embeddings)
- At least one of: OpenAI API key / Anthropic API key / Gemini API key — or use Ollama only

### 1. Clone and configure

```bash
git clone https://github.com/AbdelRahman-Madboly/Nexus-AI.git
cd Nexus-AI
cp .env.example .env
# Edit .env — add your API keys and Ollama URL
```

### 2. Pull Ollama models

```bash
ollama pull nomic-embed-text   # required — used for all embeddings
ollama pull gemma3:4b          # or any chat model you prefer
```

### 3. Start everything

```bash
docker-compose up -d
```

### 4. Verify

```bash
curl http://localhost:8000/api/health
# → {"status":"ok","components":{"database":{"status":"ok"},"ollama":{"status":"ok"},...}}
```

### 5. Ingest a document and ask a question

```bash
# Ingest a URL
curl -X POST http://localhost:8000/api/rag/ingest \
     -H "Content-Type: application/json" \
     -d '{"source": "https://example.com/your-docs"}'

# Ask a question
curl -X POST http://localhost:8000/api/rag/query \
     -H "Content-Type: application/json" \
     -d '{"query": "What does this product do?", "stream": false}'
```

### 6. Open the dashboard

```
http://localhost:3000
```

API docs (Swagger UI) at `http://localhost:8000/api/docs`

---

## Services

| Service | Port | Description |
|---|---|---|
| `nexus-api` | 8000 | FastAPI backend — all AI logic |
| `nexus-chroma` | 8001 | ChromaDB vector store |
| `nexus-ollama` | 11434 | Local Ollama LLM server |
| `nexus-n8n` | 5678 | n8n workflow automation |
| `nexus-ui` | 3000 | React dashboard |
| `nexus-openclaw` | 3456 | OpenClaw messaging gateway |

All 6 services start with a single `docker-compose up -d`.

---

## LLM Configuration

Switch backends with a single `.env` change — zero code changes required.

```bash
# Gemini (default)
LLM_BACKEND=gemini
GEMINI_API_KEY=your-key

# Claude
LLM_BACKEND=claude
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
LLM_BACKEND=openai
OPENAI_API_KEY=sk-...

# Local Ollama only — fully private
LLM_BACKEND=ollama
PRIVACY_MODE=true    # forces ALL calls to Ollama regardless of LLM_BACKEND
```

> Embeddings **always** use Ollama (`nomic-embed-text`) regardless of the LLM backend.
> This keeps ChromaDB vectors consistent across ingest and query sessions.

---

## API Reference

### Health
```http
GET /api/health
```

### RAG
```http
POST /api/rag/ingest
{"source": "https://your-url.com", "doc_type": "url"}

POST /api/rag/query
{"query": "Your question here", "top_k": 3, "stream": false}
```

### Agents
```http
POST /api/agents/lead/classify
{
  "company": "Acme Corp",
  "contact_name": "Jane Smith",
  "contact_email": "jane@acme.com",
  "source": "LinkedIn",
  "message": "We're evaluating AI CRM tools for our 50-person sales team."
}

POST /api/agents/lead/followup
{"deal_id": "your-deal-uuid"}

GET /api/agents/pipeline/report

GET /api/agents/trace/{run_id}
```

### MCP
```http
GET /api/mcp/tools       # list all 10 tools
# SSE transport at: /mcp/sse  (for Claude Desktop)
```

Full API contract at [`docs/api_contract.md`](docs/api_contract.md).

---

## Messaging Gateway (OpenClaw)

Connect Telegram, WhatsApp, or Slack to the Nexus backend without touching the dashboard.

<p align="center">
  <img src="docs/images/openclaw_flow.png" alt="OpenClaw Message Flow" width="80%"/>
</p>

**Trigger keywords:**

| Message | Routed to |
|---|---|
| "what is...", "tell me about...", anything unknown | RAG knowledge base |
| "classify lead...", "new lead from..." | Lead Classifier Agent |
| "followup for deal [uuid]" | Follow-up Writer Agent |
| "pipeline report", "kpis", "conversion" | Pipeline Reporter Agent |

Setup guide: [`openclaw/README.md`](openclaw/README.md)

---

## Claude Desktop Integration (MCP)

<p align="center">
  <img src="docs/images/mcp_demo.png" alt="MCP Claude Desktop Demo" width="80%"/>
</p>

Add this to your Claude Desktop config (`%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "nexus-ai": {
      "url": "http://localhost:8000/mcp/sse",
      "name": "Nexus-AI",
      "description": "AI CRM — leads, deals, knowledge base, pipeline agents"
    }
  }
}
```

Then ask Claude: *"How many hot leads do we have?"* or *"Draft a follow-up for deal [id]"*

10 tools available: query leads, query deals, get deal history, update deal stage, search knowledge, ingest document, draft email, schedule follow-up, pipeline KPIs, agent runs.

---

## n8n Automation Workflows

4 ready-to-import workflow JSON files in [`n8n/workflows/`](n8n/workflows/):

| Workflow | Trigger | What it does |
|---|---|---|
| `lead-intake.json` | Webhook | Classifies incoming lead → Slack + Telegram notification |
| `followup-scheduler.json` | Daily cron | Finds stale deals → drafts follow-up → Gmail |
| `pipeline-digest.json` | Monday 8AM | Pipeline report → email + Slack |
| `alert-escalation.json` | Webhook | WhatsApp + Slack alert → 4h wait → escalate |

Import via n8n UI at `http://localhost:5678`.

---

## Database Schema

SQLite (WAL mode, async via aiosqlite). Four tables:

```sql
leads       — id, company, contact_name, contact_email, source, stage, score, timestamps
deals       — id, lead_id (FK), stage, value, owner, last_contact, timestamps
agent_runs  — id, agent_name, run_id, input_json, output_json, status, timestamps
rag_queries — id, query_text, response_text, sources_json, latency_ms, model_used, created_at
```

Lead stages: `new_lead` · `hot_lead` (≥80) · `nurture` (50–79) · `proposal` · `closed_won` · `closed_lost` · `disqualified` (<50) · `escalated`

---

## Engineering Principles

Every file in the project follows these rules without exception:

1. **LLM routing** — all LLM calls go through `api/llm/llm_router.py`. No SDK imports in feature code.
2. **Privacy mode** — `PRIVACY_MODE=true` routes everything to Ollama at the config layer.
3. **Config** — all settings from `api/config.py` (pydantic-settings). Zero hardcoded values.
4. **Database** — SQLite only, WAL mode, async via aiosqlite.
5. **Agents** — all agents use LangGraph `StateGraph` + `SqliteSaver`. Every run logged to `agent_runs`.
6. **API models** — every endpoint has a Pydantic v2 request and response model. No `dict` or `Any`.
7. **Async** — `async/await` throughout for all I/O.
8. **No vendor lock-in** — switch LLM backend via single `.env` change. Zero code changes.

---

## Project Structure

```
Nexus-AI/
├── api/
│   ├── config.py           # pydantic-settings singleton, PRIVACY_MODE enforcement
│   ├── database.py         # SQLite WAL, 4 tables, get_db() context manager
│   ├── main.py             # FastAPI app, lifespan, health endpoint, MCP mount
│   ├── llm/                # LLM router + OpenAI / Claude / Gemini / Ollama clients
│   ├── rag/                # Document ingestor + hybrid retriever
│   ├── agents/             # 3 LangGraph agents + shared graph utilities
│   ├── mcp/                # FastMCP server, 10 tools, SSE transport
│   └── routers/            # rag_router · agent_router · mcp_router
├── openclaw/
│   ├── index.js            # Gateway entry: Telegram + WhatsApp + Slack + intent router
│   ├── skills/             # nexus-rag · nexus-leads · nexus-pipeline
│   ├── SOUL.md             # Assistant persona definition
│   └── MEMORY.md           # Company context seed
├── n8n/workflows/          # 4 n8n workflow JSON files (import via UI)
├── dashboard/              # React 18 + Vite + TypeScript + TailwindCSS
├── tests/                  # 35 tests — database · RAG · agents · MCP · integration
├── docs/                   # Architecture · API contract · demo script
└── docker-compose.yml      # 6 services, single-command deploy
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI · Python 3.12 · Pydantic v2 · uvicorn |
| Agents | LangGraph 1.x · LangChain 1.x · SQLite checkpointer |
| RAG | ChromaDB · Ollama embeddings · BM25 · CrossEncoder reranking |
| LLM | Ollama · OpenAI · Anthropic Claude · Google Gemini |
| Messaging | Node.js · Telegram Bot API · Twilio (WhatsApp) · Slack Bolt SDK |
| MCP | FastMCP · SSE transport |
| Automation | n8n |
| Frontend | React 18 · Vite · TypeScript · TailwindCSS |
| Database | SQLite (WAL mode · aiosqlite) |
| Infrastructure | Docker Compose · 6 services |

---

## Test Coverage

```bash
python -m pytest tests/ -v
```

| Suite | Tests | Status |
|---|---|---|
| `test_database.py` | 18 | ✅ Passing |
| `test_rag.py` | 10 | ✅ Passing |
| `test_agents.py` | 7 | ✅ Passing |
| `test_mcp.py` | 6 | ✅ Passing |
| `test_openclaw_skills.js` | 5 | ✅ Passing (integration) |

All agent and MCP tests are fully mocked — no Ollama, Gemini, or ChromaDB required to run the Python suite.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker compose` not found | Use `docker-compose` (hyphen) |
| Ollama unreachable from container | Check `OLLAMA_BASE_URL` in `.env` — WSL2 gateway IP changes on reboot |
| Uvicorn hangs 3–5 min on first start | CrossEncoder model (~90MB) downloading. Wait once — cached forever after. |
| ChromaDB `KeyError: '_type'` | Do not pass `metadata=` to `get_or_create_collection()` |
| Gemini 429 on test suite | Free tier = 5 req/min. Set `LLM_BACKEND=ollama` for bulk testing. |
| `langchain-core` version conflict | Upgrade full langchain stack to 1.x (see `api/requirements.txt`) |
| `GraphRecursionError` in agent | Increment state counters inside node return dicts, not inside edge functions |
| Telegram `409 Conflict` | Two bot instances running — `pkill -f "node index.js"` then restart |
| RAG returns empty answer | No documents ingested yet — run `POST /api/rag/ingest` first |

---

## License

MIT — see [LICENSE](LICENSE)

---

**Owner:** Abdel Rahman M. El-Saied
**GitHub:** [github.com/AbdelRahman-Madboly/Nexus-AI](https://github.com/AbdelRahman-Madboly/Nexus-AI)