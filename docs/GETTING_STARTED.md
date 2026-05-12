# Nexus-AI — Getting Started Guide
> Everything you need to go from a fresh clone to a fully running system.
> Owner: Abdel Rahman M. El-Saied

---

## Overview

Nexus-AI runs as **6 Docker services** orchestrated by `docker-compose`. The only thing that runs *outside* Docker is **Ollama**, which must run on the Windows host so it can use the GPU (RTX 4050).

```
Windows host     → Ollama (GPU inference)
WSL2 / Ubuntu    → Docker services (API, ChromaDB, n8n, Dashboard, OpenClaw)
```

The whole startup sequence is:
1. Start Ollama on Windows (once per session)
2. Check the WSL2 → Windows IP (changes on reboot)
3. Update `.env` if the IP changed
4. `docker-compose up -d` in WSL2
5. Verify health
6. Open the dashboard

---

## Part 1 — First-Time Setup

> Do this once. Skip to Part 2 on subsequent sessions.

### 1.1 — Clone the repo (WSL2 terminal)

```bash
cd /mnt/c/Dan_WS
git clone https://github.com/AbdelRahman-Madboly/Nexus-AI.git
cd Nexus-AI
```

### 1.2 — Copy and configure `.env`

```bash
cp .env.example .env
```

Open `.env` in your editor and set at minimum:

```bash
LLM_BACKEND=gemini           # or: ollama | claude | openai
GEMINI_API_KEY=your-key-here # skip if using ollama only

OLLAMA_BASE_URL=http://172.29.208.1:11434   # see step 1.3 below
OLLAMA_MODEL=gemma3:4b
OLLAMA_EMBED_MODEL=nomic-embed-text

PRIVACY_MODE=false           # set true to force all calls to Ollama
```

### 1.3 — Get your Windows host IP (WSL2)

This IP is how Docker containers inside WSL2 reach the Windows Ollama server. It **changes on every reboot** — you must update `.env` each session if it has changed.

```bash
ip route | grep default | awk '{print $3}'
# Example output: 172.29.208.1
```

Set `OLLAMA_BASE_URL=http://<that-ip>:11434` in `.env`.

### 1.4 — Pull Ollama models (Windows CMD / PowerShell)

Open a Windows terminal and run:

```cmd
ollama pull nomic-embed-text
ollama pull gemma3:4b
```

`nomic-embed-text` is **required** for all RAG and embedding operations regardless of which LLM backend you choose. `gemma3:4b` is the default chat model when using the Ollama backend.

### 1.5 — Activate the Python venv (WSL2)

```bash
cd /mnt/c/Dan_WS/Nexus-AI
python3 -m venv venv              # only needed if venv doesn't exist yet
source venv/bin/activate
pip install -r api/requirements.txt   # only on first setup
```

---

## Part 2 — Every Session Startup

Run these steps in order every time you start a new working session.

### Step 1 — Start Ollama on Windows (Windows CMD)

Open **Windows Command Prompt** (not WSL, not PowerShell) and run:

```cmd
set OLLAMA_HOST=0.0.0.0
ollama serve
```

**Why `set OLLAMA_HOST=0.0.0.0`?**
By default Ollama binds to `127.0.0.1` (localhost) on Windows, which is unreachable from WSL2 Docker containers. Setting `OLLAMA_HOST=0.0.0.0` makes Ollama listen on all interfaces including the WSL2 bridge network.

Leave this CMD window open. Minimise it. Do not close it.

**Verify Ollama is reachable from WSL2:**

```bash
# In WSL2 terminal:
curl http://172.29.208.1:11434
# Expected: "Ollama is running"
```

If this returns "connection refused", double-check:
- Ollama is running in Windows CMD with `OLLAMA_HOST=0.0.0.0`
- The IP matches: `ip route | grep default | awk '{print $3}'`
- Windows Firewall is not blocking port 11434 (add an inbound rule if needed)

### Step 2 — Check the IP hasn't changed (WSL2)

```bash
ip route | grep default | awk '{print $3}'
```

If this IP is **different** from `OLLAMA_BASE_URL` in your `.env`, update `.env` now.

```bash
# Quick update (replace 172.29.208.1 with your new IP):
sed -i 's|OLLAMA_BASE_URL=.*|OLLAMA_BASE_URL=http://172.29.208.1:11434|' .env
```

### Step 3 — Start all Docker services (WSL2)

```bash
cd /mnt/c/Dan_WS/Nexus-AI
source venv/bin/activate

docker-compose down && docker-compose up -d
```

**Important:** Always do `down && up`, never `docker-compose up -d nexus-api` alone. The single-service command has a known `KeyError: 'ContainerConfig'` bug on this Docker Compose version.

First start after a `--build` takes 60–90 seconds. Subsequent starts are under 10 seconds.

### Step 4 — Verify all 6 services are Up

```bash
docker-compose ps
```

Expected output:

```
NAME              STATUS
nexus-api         Up
nexus-chroma      Up
nexus-ollama      Up
nexus-n8n         Up
nexus-ui          Up
nexus-openclaw    Up
```

If any service shows `Exit` or `Restarting`, check its logs:

```bash
docker-compose logs -f nexus-api    # replace with the failing service name
```

### Step 5 — Health check

```bash
curl http://localhost:8000/api/health
```

Expected:

```json
{
  "status": "ok",
  "components": {
    "database":    {"status": "ok", "detail": null},
    "ollama":      {"status": "ok", "detail": null},
    "llm_backend": {"status": "ok", "detail": "gemini"}
  }
}
```

If `ollama` shows `degraded`:
- Check Ollama is running in Windows CMD with `OLLAMA_HOST=0.0.0.0`
- Check the IP in `.env` matches `ip route | grep default | awk '{print $3}'`

### Step 6 — Ingest documents (first time or after data wipe)

The RAG system needs at least one document ingested before you can ask questions. On a fresh setup or after `docker-compose down -v` (which wipes ChromaDB), run:

```bash
curl -X POST http://localhost:8000/api/rag/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "https://projecx.io"}'
```

Expected response:

```json
{"source":"https://projecx.io","doc_type":"url","chunk_count":8,"duration_ms":28000}
```

You can ingest as many documents as you want — the knowledge base accumulates across ingests. To ingest a local file, upload it through the dashboard's Ingest button, or POST with a file path.

### Step 7 — Open the dashboard

```
http://localhost:3000
```

The dashboard has three pages:
- **RagChat** (default) — ask questions, see cited source chunks
- **AgentTracer** — inspect LangGraph agent run logs by `run_id`
- **Pipeline** — CRM KPIs, stage distribution, generate executive digest

---

## Part 3 — Using the System

### 3.1 — RAG Knowledge Base

**From the dashboard:**
1. Go to `http://localhost:3000` (RagChat page)
2. Click **Ingest** (top right) → enter a URL or upload a file → click Ingest
3. Type your question in the chat input → press Enter
4. The answer appears with ⚡ latency badge; source chunks appear in the right panel

**First query after startup is slow** (5–30 seconds) because the CrossEncoder reranking model loads from cache. All subsequent queries are ~1–2 seconds.

**From the API:**

```bash
# Ingest a URL
curl -X POST http://localhost:8000/api/rag/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "https://your-url.com"}'

# Ask a question
curl -X POST http://localhost:8000/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What does this product do?", "top_k": 3}'
```

### 3.2 — Lead Classifier Agent

Submit a new lead and get a classification (hot / nurture / disqualified / escalated), a 0–100 score, and full reasoning.

```bash
curl -X POST http://localhost:8000/api/agents/lead/classify \
  -H "Content-Type: application/json" \
  -d '{
    "company": "Acme Corp",
    "contact_name": "Jane Smith",
    "contact_email": "jane@acme.com",
    "source": "LinkedIn",
    "message": "We want to deploy your CRM for 200 agents. C-level approved, Q3 budget confirmed."
  }'
```

Expected:

```json
{
  "stage": "hot_lead",
  "score": 88,
  "reasoning": "High intent: C-level approval, budget confirmed, 200-agent scale...",
  "run_id": "1dd1b8d6-3502-4637-af63-90afa0e052f1"
}
```

Copy the `run_id` and paste it into the **AgentTracer** page on the dashboard to inspect the full 5-node reasoning trace.

**Scoring thresholds:**

| Score | Stage |
|---|---|
| ≥ 80 | `hot_lead` |
| 50 – 79 | `nurture` |
| < 50 | `disqualified` |
| Any (with red flags) | `escalated` |

### 3.3 — Follow-up Writer Agent

Generate a personalised follow-up email for an existing deal. The agent pulls deal history from the database and product context from the RAG knowledge base.

```bash
curl -X POST http://localhost:8000/api/agents/lead/followup \
  -H "Content-Type: application/json" \
  -d '{"deal_id": "your-deal-uuid-here"}'
```

Expected:

```json
{
  "draft": "Dear Jane, following our conversation about the Revenyu CRM deployment...",
  "review_score": 82,
  "run_id": "..."
}
```

The agent self-reviews its own draft and retries (up to 2 times) if `review_score < 70`.

### 3.4 — Pipeline Reporter Agent

Generate a full pipeline report with conversion rate, average deal age, stage distribution, bottleneck analysis, and an LLM-written executive digest.

```bash
curl http://localhost:8000/api/agents/pipeline/report
```

Or click **Generate Report** on the Pipeline page in the dashboard.

### 3.5 — Claude Desktop (MCP)

Connect Claude Desktop to query the live database in plain English.

**Config file location:**
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`

**Add this to the config:**

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

**After saving:** fully quit Claude Desktop (right-click system tray → Quit) and relaunch. Do not just close the window.

**Verify the connection:** Open Claude Desktop and ask:
```
How many leads are in the Nexus pipeline?
```

Claude should call the `nexus_query_leads` tool and return a live count from your SQLite database.

**10 available tools:** `nexus_query_leads` · `nexus_query_deals` · `nexus_get_deal_history` · `nexus_update_deal_stage` · `nexus_search_knowledge` · `nexus_ingest_document` · `nexus_draft_email` · `nexus_schedule_followup` · `nexus_pipeline_kpis` · `nexus_agent_runs`

### 3.6 — Messaging Channels (OpenClaw)

Send messages to the configured Telegram bot, WhatsApp number, or Slack workspace. The gateway routes by keyword:

| What you send | Where it goes |
|---|---|
| Anything informational | RAG knowledge base |
| "classify lead: [details]" | Lead Classifier Agent |
| "followup for deal [uuid]" | Follow-up Writer Agent |
| "pipeline report" / "kpis" | Pipeline Reporter Agent |

**Telegram quick test:**
Send `pipeline report` to your configured Telegram bot. You should receive a formatted KPI summary within 5–10 seconds.

### 3.7 — n8n Workflows

Open n8n at `http://localhost:5678`.

**Import workflows (first time):**
1. Click **Workflows** in the left sidebar
2. Click **Import** (top right)
3. Import each file from `n8n/workflows/`:
   - `lead-intake.json`
   - `followup-scheduler.json`
   - `pipeline-digest.json`
   - `alert-escalation.json`
4. After importing each, click **Activate** (toggle top right, turns green)

**Trigger lead intake manually:**

```bash
curl -X POST http://localhost:5678/webhook/lead-intake \
  -H "Content-Type: application/json" \
  -d '{
    "company": "Test Corp",
    "contact_name": "Test User",
    "contact_email": "test@test.com",
    "source": "manual",
    "message": "Testing the n8n lead intake workflow."
  }'
```

**Trigger alert escalation manually:**

```bash
curl -X POST http://localhost:5678/webhook/alert-escalation \
  -H "Content-Type: application/json" \
  -d '{
    "deal_id": "test-deal-001",
    "company": "Risky Corp",
    "contact_name": "Test User",
    "escalation_level": "critical",
    "reason": "Contract dispute",
    "assigned_to": "Abdel Rahman"
  }'
```

### 3.8 — Swagger API Docs

All endpoints are documented and testable at:

```
http://localhost:8000/api/docs
```

This is the fastest way to explore and test any endpoint without writing curl commands.

---

## Part 4 — Switching LLM Backends

Edit `.env` and restart the API. Zero code changes required.

```bash
# Use Gemini (default — fast, free tier)
LLM_BACKEND=gemini
GEMINI_API_KEY=your-key

# Use Claude
LLM_BACKEND=claude
ANTHROPIC_API_KEY=sk-ant-...

# Use OpenAI
LLM_BACKEND=openai
OPENAI_API_KEY=sk-...

# Use local Ollama only — fully private
LLM_BACKEND=ollama
PRIVACY_MODE=true     # forces ALL calls to Ollama, ignores LLM_BACKEND
```

After editing `.env`:

```bash
docker-compose down && docker-compose up -d
```

**Note:** Embeddings always use Ollama `nomic-embed-text` regardless of `LLM_BACKEND`. This keeps ChromaDB vectors consistent. Do not change `OLLAMA_EMBED_MODEL` unless you re-ingest all documents.

---

## Part 5 — Dev Mode (faster iteration)

For active development, run FastAPI and the dashboard directly without Docker (faster feedback, hot reload).

```bash
# Terminal 1 — stop Docker services that conflict, then run FastAPI with hot reload
docker-compose stop nexus-api nexus-ui
source venv/bin/activate
uvicorn api.main:app --reload --port 8000

# Terminal 2 — Vite dev server with HMR
cd dashboard && npm run dev
# Dashboard now at http://localhost:5173 (Vite port, not 3000)

# Terminal 3 — keep ChromaDB running in Docker (required for RAG)
docker-compose up -d nexus-chroma
```

When done with dev mode, go back to full Docker:

```bash
docker-compose down && docker-compose up -d --build
```

---

## Part 6 — Rebuild After Code Changes

```bash
# Rebuild only the API image (after Python code changes)
docker-compose down && docker-compose up -d --build nexus-api

# Rebuild only the dashboard (after React code changes)
docker-compose down && docker-compose up -d --build nexus-ui

# Rebuild everything (after requirements.txt or Dockerfile changes)
docker-compose down && docker-compose up -d --build

# Force clean rebuild — no layer cache
docker-compose down
docker rmi nexus-ai-nexus-api nexus-ai-nexus-ui
docker-compose up -d --build
```

---

## Part 7 — Common Problems

### Ollama unreachable — "connection refused"

```
Symptom: curl http://172.29.208.1:11434 → connection refused
Cause A: Ollama not running on Windows
Cause B: Ollama bound to localhost only (missing OLLAMA_HOST=0.0.0.0)
Cause C: IP has changed since last reboot
Fix A:   Open Windows CMD → set OLLAMA_HOST=0.0.0.0 && ollama serve
Fix B:   Same as Fix A — always set OLLAMA_HOST before ollama serve
Fix C:   ip route | grep default | awk '{print $3}' → update .env → docker-compose down && up
```

### First RAG query takes 30+ seconds

```
Cause:  CrossEncoder model (~90MB) loading from HuggingFace cache on first access.
        This happens once per uvicorn process start (Docker or direct).
Action: Wait. All subsequent queries will be 1–2 seconds.
Fix if recurring: ensure ~/.cache/huggingface is volume-mounted in docker-compose.yml
                  (it already is in the current config).
```

### RAG returns "I don't have that information"

```
Cause A: No documents ingested yet
Cause B: ChromaDB container not running (docker-compose ps → check nexus-chroma)
Cause C: ChromaDB data wiped (docker-compose down -v was run)
Fix A:   POST /api/rag/ingest with a source URL or file
Fix B:   docker-compose up -d nexus-chroma
Fix C:   Re-ingest all documents after a -v wipe — data is not recoverable
```

### ChromaDB `KeyError: '_type'`

```
Cause: metadata= passed to get_or_create_collection() in chromadb 0.6.3
Fix:   This is already fixed in the codebase. If you see this, you may have
       edited ingestor.py and added a metadata= argument. Remove it.
```

### n8n webhook returns 404

```
Cause: Workflow is imported but not activated
Fix:   n8n UI (http://localhost:5678) → open the workflow → toggle Activate (top right)
```

### Claude Desktop shows no tools / can't connect

```
Cause A: Config not saved correctly or wrong URL
Cause B: Claude Desktop window closed but process still running (old config in memory)
Fix A:   Check %APPDATA%\Claude\claude_desktop_config.json — URL must be http://localhost:8000/mcp/sse
Fix B:   Right-click Claude Desktop in system tray → Quit → relaunch
Note:    nexus-api must be running before Claude Desktop starts the MCP connection
```

### `docker-compose` not found

```
Cause: Docker Compose v2 plugin not installed on this system
Fix:   Use docker-compose (with hyphen) — NOT docker compose (with space)
```

### `KeyError: 'ContainerConfig'` on docker-compose up

```
Cause: docker-compose 1.29.2 bug when targeting a single service with existing container metadata
Fix:   Always use: docker-compose down && docker-compose up -d
       Never use:  docker-compose up -d nexus-api (single service)
```

---

## Part 8 — Stopping the System

```bash
# Stop all services, keep data intact
docker-compose down

# Stop all services AND wipe all volume data (ChromaDB vectors, n8n data)
# WARNING: you will need to re-ingest all documents after this
docker-compose down -v

# Stop a single service without taking down the whole stack
docker-compose stop nexus-api
```

Stop Ollama on Windows by closing the CMD window where `ollama serve` is running, or:

```cmd
# Windows CMD
taskkill /f /im ollama.exe
```

---

*Nexus-AI Getting Started Guide — v1.0.0*
*Owner: Abdel Rahman M. El-Saied*
*GitHub: github.com/AbdelRahman-Madboly/Nexus-AI*
