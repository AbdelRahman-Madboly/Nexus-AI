# Nexus-AI

**AI-Augmented Business Operations Platform**
Built to demonstrate production-quality AI engineering — RAG, LangGraph agents, messaging AI, MCP, n8n, and a React dashboard, all running locally with a single command.

> Portfolio project targeting [Projecx](https://projecx.io) — a Business Development Studio in Abu Dhabi building AI-powered SaaS products.

---

## What It Does

Nexus is a self-hosted platform that connects AI to the full lifecycle of a B2B sales pipeline:

| Component | What it does |
|---|---|
| **RAG Engine** | Ingest any document (PDF, URL, DOCX, Markdown). Ask business questions and get cited, grounded answers. |
| **Lead Classifier Agent** | Drop in a lead and get a classification (hot/nurture/disqualified/escalated), a score, and the reasoning — in under 3 seconds. |
| **Follow-up Writer Agent** | Give it a deal ID and get a personalized follow-up email that references facts from the deal history. Self-reviews its own draft and retries if quality is below threshold. |
| **Pipeline Reporter Agent** | Ask for a pipeline report and get conversion rate, average deal age, stage distribution, and bottleneck analysis — plus an LLM-written executive digest. |
| **OpenClaw Gateway** | Send "classify this lead" via Telegram or WhatsApp. The AI agent classifies it and replies — no dashboard needed. |
| **MCP Server** | Open Claude Desktop and ask "How many hot leads do we have?" — it queries your live SQLite database and answers. |
| **n8n Workflows** | 4 business automations: lead intake, stale-deal follow-up, Monday pipeline digest, and alert escalation. |
| **React Dashboard** | RAG chat with streaming and source citations, LangGraph agent trace visualizer, and pipeline Kanban board. |

---

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Ollama running locally (or accessible on network)
- One of: OpenAI API key / Anthropic API key / Gemini API key (or use Ollama only)

### 1. Clone and configure
```bash
git clone https://github.com/AbdelRahman-Madboly/Nexus-AI.git
cd Nexus-AI
cp .env.example .env
# Edit .env — add your API keys and Ollama URL
```

### 2. Pull Ollama models
```bash
ollama pull nomic-embed-text   # required for RAG
ollama pull gemma3:4b          # or any model you prefer
```

### 3. Start everything
```bash
docker-compose up -d
```

### 4. Verify
```bash
curl http://localhost:8000/api/health
# {"status":"ok","components":{"database":{"status":"ok"},"ollama":{"status":"ok"}}}
```

### 5. Open the dashboard
```
http://localhost:3000
```

### 6. API docs
```
http://localhost:8000/api/docs
```

---

## Architecture

```
FastAPI Gateway (port 8000)
├── RAG Engine
│   ├── Document Ingestor  — PDF/MD/DOCX/URL → chunk → embed → ChromaDB
│   └── Hybrid Retriever   — semantic + BM25 → cross-encoder rerank → LLM → stream
├── LangGraph Agents (SQLite checkpointer)
│   ├── Lead Classifier    — 5 nodes, score-based routing (hot/nurture/disqualified/escalated)
│   ├── Follow-up Writer   — 5 nodes, self-review loop (max 2 retries, threshold 70)
│   └── Pipeline Reporter  — 5 nodes, 4 KPI sections, rule-based bottleneck detection
├── MCP Server (FastMCP)   — 10 tools, Claude Desktop integration
├── OpenClaw Gateway (port 3456)
│   └── Skills: nexus-rag · nexus-leads · nexus-pipeline
│   └── Channels: Telegram · WhatsApp · Slack
├── n8n Automation (port 5678)
│   └── 4 workflows: lead-intake · followup-scheduler · pipeline-digest · alert-escalation
├── React Dashboard (port 3000)
│   └── RagChat · AgentTracer · Pipeline Kanban
└── LLM Router
    └── openai | claude | gemini | ollama (PRIVACY_MODE=true → always Ollama)
```

**All services start with:** `docker-compose up -d`

---

## Services

| Service | Port | Description |
|---|---|---|
| nexus-api | 8000 | FastAPI backend — all AI logic |
| nexus-chroma | 8001 | ChromaDB vector store |
| nexus-ollama | 11434 | Ollama local LLM |
| nexus-n8n | 5678 | n8n workflow automation |
| nexus-ui | 3000 | React dashboard |
| nexus-openclaw | 3456 | OpenClaw messaging gateway |

---

## LLM Backend Configuration

Switch backends with a single `.env` change — zero code changes:

```bash
# Use Gemini
LLM_BACKEND=gemini
GEMINI_API_KEY=your-key-here

# Use Claude
LLM_BACKEND=claude
ANTHROPIC_API_KEY=sk-ant-...

# Use OpenAI
LLM_BACKEND=openai
OPENAI_API_KEY=sk-...

# Use local Ollama only (privacy mode)
LLM_BACKEND=ollama
PRIVACY_MODE=true              # ← forces ALL calls to Ollama regardless of LLM_BACKEND
```

Embeddings always use Ollama (`nomic-embed-text`) regardless of backend.
This ensures ChromaDB vectors stay consistent across ingest and query.

---

## Key API Endpoints

### Health check
```bash
GET /api/health
```

### Ingest a document
```bash
POST /api/rag/ingest
{"source": "https://projecx.io", "doc_type": "url"}
```

### Ask a question
```bash
POST /api/rag/query
{"query": "What percentage of workflows is Projecx integrating AI into?", "stream": false}
```

### Classify a lead
```bash
POST /api/agents/lead/classify
{
  "company": "Acme Corp",
  "contact_name": "Jane Smith",
  "source": "LinkedIn",
  "message": "We are looking for an AI CRM solution for our 50-person sales team."
}
```

### Generate a follow-up email
```bash
POST /api/agents/lead/followup
{"deal_id": "your-deal-uuid"}
```

### Get pipeline report
```bash
GET /api/agents/pipeline/report
```

### Get agent trace
```bash
GET /api/agents/trace/{run_id}
```

---

## Demo Script (10 Minutes)

1. **Start:** `docker-compose up -d` → confirm all 6 services running
2. **RAG:** Ingest Projecx website → ask "What is Revenyu?" → get cited answer
3. **Agents:** POST test lead → watch classification + score → check trace in dashboard
4. **Messaging:** Send "Classify this lead: [Acme Corp, CEO, wants AI CRM]" via Telegram → response arrives
5. **MCP:** Open Claude Desktop → "How many hot leads?" → live answer from SQLite
6. **Automation:** Trigger Lead Intake webhook in n8n → Slack message + Telegram notification appear

---

## Project Structure

```
Nexus-AI/
├── api/                    # FastAPI backend
│   ├── config.py           # pydantic-settings, PRIVACY_MODE, LLM routing
│   ├── database.py         # SQLite WAL, 4 tables
│   ├── main.py             # FastAPI app + health endpoint
│   ├── llm/                # LLM router + 4 backend clients
│   ├── rag/                # Document ingestor + hybrid retriever
│   ├── agents/             # 3 LangGraph agents + shared graph utils
│   ├── mcp/                # FastMCP server, 10 tools
│   └── routers/            # API route handlers
├── openclaw/               # OpenClaw gateway config + skills
├── n8n/workflows/          # 4 n8n workflow JSON files
├── dashboard/              # React + Vite + TailwindCSS
├── tests/                  # pytest test suites (35/35 passing)
├── docs/                   # Architecture + API contract + demo script
└── docker-compose.yml      # 6 services
```

---

## Tech Stack

Python · FastAPI · LangGraph · LangChain · ChromaDB · SQLite · Ollama ·
OpenClaw · n8n · FastMCP · React · Vite · TypeScript · TailwindCSS · Docker

---

## Build Progress

| Phase | Status | Description |
|---|---|---|
| Phase 0 — Foundation | ✅ v0.1.0 | Config, DB, LLM router, FastAPI, Docker |
| Phase 1 — RAG Engine | ✅ v0.2.0 | Document ingestor + hybrid retriever (semantic + BM25 + rerank) |
| Phase 2 — Agents | ✅ v0.3.0 | Lead Classifier + Follow-up Writer + Pipeline Reporter |
| Phase 3 — MCP Server | ⬜ v0.4.0 | FastMCP, 10 tools, Claude Desktop |
| Phase 4 — OpenClaw | ⬜ v0.5.0 | Messaging gateway, 3 skills, Telegram |
| Phase 5 — n8n | ⬜ v0.6.0 | 4 business automation workflows |
| Phase 6 — Dashboard | ⬜ v0.7.0 | React dashboard, 3 pages |
| Phase 7 — Integration | ⬜ v1.0.0 | Full demo, LinkedIn post, submit |

---

## Test Coverage

| Suite | Tests | Status |
|---|---|---|
| `tests/test_database.py` | 18 | ✅ Passing |
| `tests/test_rag.py` | 10 | ✅ Passing |
| `tests/test_agents.py` | 7 | ✅ Passing |

All agent tests are fully mocked — no Ollama, Gemini, or ChromaDB required to run the suite.

---

## Why Projecx

Projecx is building AI-powered SaaS products (Revenyu CRM, Bandora CMS) with a confirmed tech stack
that maps directly to Nexus: Python, FastAPI, Ollama, n8n, Docker, LangGraph, React, and messaging
integrations via Telegram/WhatsApp/Slack. Nexus demonstrates that I already understand and can build
exactly the kind of AI engineering they are doing.

---

**Owner:** Abdel Rahman M. El-Saied
**GitHub:** [github.com/AbdelRahman-Madboly/Nexus-AI](https://github.com/AbdelRahman-Madboly/Nexus-AI)
**License:** MIT