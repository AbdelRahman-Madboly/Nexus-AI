# Nexus-AI — API Contract
> Full reference for every HTTP endpoint in the FastAPI backend.
> Base URL: `http://localhost:8000`
> Interactive docs: `http://localhost:8000/api/docs` (Swagger UI)
> Owner: Abdel Rahman M. El-Saied

---

## Conventions

- All request and response bodies are JSON (`Content-Type: application/json`)
- All endpoints are prefixed with `/api`
- Timestamps are UTC strings in SQLite ISO format: `2026-05-11 21:59:03`
- UUIDs are lowercase with hyphens: `1dd1b8d6-3502-4637-af63-90afa0e052f1`
- Scores are integers 0–100
- HTTP errors follow FastAPI's default format: `{"detail": "..."}`
- Streaming responses use `text/event-stream` (SSE)

---

## Health

### `GET /api/health`

Check the status of all system components. Safe to call without side effects.

**Response `200 OK`:**

```json
{
  "status": "ok",
  "components": {
    "database":    {"status": "ok",       "detail": null},
    "ollama":      {"status": "ok",       "detail": null},
    "llm_backend": {"status": "ok",       "detail": "gemini"}
  }
}
```

`status` is `"ok"` only if both `database` and `ollama` are healthy. Otherwise `"degraded"`.

`llm_backend.detail` contains the active backend name (`gemini` | `claude` | `openai` | `ollama`).
If `PRIVACY_MODE=true`, it will always show `"ollama"` regardless of `LLM_BACKEND`.

**Response `200 OK` (degraded):**

```json
{
  "status": "degraded",
  "components": {
    "database":    {"status": "ok",       "detail": null},
    "ollama":      {"status": "error",    "detail": "Connection refused"},
    "llm_backend": {"status": "ok",       "detail": "gemini"}
  }
}
```

---

## RAG Engine

### `POST /api/rag/ingest`

Ingest a document into the ChromaDB knowledge base. Chunks the source, embeds with
Ollama `nomic-embed-text`, and upserts into the `nexus_knowledge` collection.
Re-ingesting the same source is safe — chunk IDs are deterministic (`sha256(source:index)[:16]`)
so upsert replaces rather than duplicates.

**Request body:**

```json
{
  "source":   "https://projecx.io",
  "doc_type": "url",
  "metadata": {}
}
```

| Field | Type | Required | Values | Default |
|---|---|---|---|---|
| `source` | string | ✅ | URL, file path, or raw text | — |
| `doc_type` | string | ❌ | `url` `pdf` `docx` `md` `txt` `text` `auto` | `auto` |
| `metadata` | object | ❌ | any key-value pairs | `{}` |

`doc_type: "auto"` infers type from the URL prefix (`http://` → `url`) or file extension.

**Response `200 OK`:**

```json
{
  "source":     "https://projecx.io",
  "doc_type":   "url",
  "chunk_count": 8,
  "duration_ms": 28005
}
```

**Errors:**

| Code | Condition |
|---|---|
| `400` | Source file not found (`FileNotFoundError`) |
| `422` | Document loaded but produced zero chunks |
| `500` | ChromaDB unavailable or embed failure |

**Example:**

```bash
curl -X POST http://localhost:8000/api/rag/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "https://projecx.io"}'
```

---

### `POST /api/rag/query`

Query the knowledge base. Runs hybrid semantic + BM25 retrieval, CrossEncoder reranking,
and LLM answer generation. Logs the query to `rag_queries` table.

**Request body:**

```json
{
  "query":  "What is Revenyu?",
  "top_k":  3,
  "stream": false
}
```

| Field | Type | Required | Default |
|---|---|---|---|
| `query` | string | ✅ | — |
| `top_k` | integer | ❌ | `3` |
| `stream` | boolean | ❌ | `false` |

`stream: true` is accepted for API compatibility but currently behaves identically to `false`.
SSE streaming is deferred to a future release.

**Response `200 OK`:**

```json
{
  "answer": "Revenyu is a next-generation CRM platform purpose-built for the real estate sector in the UAE and broader GCC region [1].",
  "sources": [
    {
      "id":       "1e20e5106bd9f88a",
      "text":     "Revenyu is a next-generation CRM platform...",
      "metadata": {"source": "https://projecx.io", "chunk_index": 2},
      "score":    6.45
    },
    {
      "id":       "5b71b29473aa530f",
      "text":     "The platform integrates AI agents...",
      "metadata": {"source": "https://projecx.io", "chunk_index": 5},
      "score":    -11.02
    }
  ],
  "latency_ms": 1521
}
```

`score` is the CrossEncoder relevance score. Positive = high relevance, negative = low.
The LLM answer cites sources by number `[1]`, `[2]`, `[3]` corresponding to array index + 1.

If the knowledge base is empty or ChromaDB is down, `answer` is
`"I don't have that information in the knowledge base."` with `sources: []`.

**Errors:**

| Code | Condition |
|---|---|
| `500` | RAG pipeline failure (logged server-side) |

**Example:**

```bash
curl -X POST http://localhost:8000/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is Revenyu?", "top_k": 3}'
```

---

## Agents

All agent endpoints are async. Execution time varies: Lead Classifier ~3s, Follow-up
Writer ~5–10s, Pipeline Reporter ~10–20s. Set client timeouts accordingly (90s recommended).

Every agent run is logged to the `agent_runs` table. Use the returned `run_id` to retrieve
the full trace via `GET /api/agents/trace/{run_id}`.

---

### `POST /api/agents/lead/classify`

Run the Lead Classifier LangGraph agent. Executes 5 nodes:
`classify_intent` → `retrieve_context` → `enrich_lead` → `score_lead` → `route_to_pipeline`

Writes a `leads` record to SQLite on completion.

**Request body:**

```json
{
  "company":       "Emirates Real Estate Group",
  "contact_name":  "Khalid Al Mansouri",
  "contact_email": "khalid@ereg.ae",
  "source":        "LinkedIn",
  "message":       "We want Revenyu CRM for 300 agents. C-level approved, Q3 budget confirmed."
}
```

| Field | Type | Required |
|---|---|---|
| `company` | string | ✅ |
| `contact_name` | string | ✅ |
| `contact_email` | string | ❌ |
| `source` | string | ✅ |
| `message` | string | ✅ |

**Response `200 OK`:**

```json
{
  "stage":     "hot_lead",
  "score":     90,
  "reasoning": "High intent: C-level approval, Q3 budget confirmed, 300-agent deployment scale. No red flags detected.",
  "run_id":    "1dd1b8d6-3502-4637-af63-90afa0e052f1"
}
```

**Stage values and thresholds:**

| Stage | Condition |
|---|---|
| `hot_lead` | `score >= 80` |
| `nurture` | `score 50–79` |
| `disqualified` | `score < 50` |
| `escalated` | Red flags present (e.g. `budget_approved` keyword triggers manual review) |

**Errors:**

| Code | Condition |
|---|---|
| `422` | Missing required fields |
| `500` | LangGraph execution failure or LLM unavailable |

**Example:**

```bash
curl -X POST http://localhost:8000/api/agents/lead/classify \
  -H "Content-Type: application/json" \
  -d '{
    "company": "Acme Corp",
    "contact_name": "Jane Smith",
    "contact_email": "jane@acme.com",
    "source": "website",
    "message": "We need an AI CRM for 50 agents. Evaluating options."
  }'
```

---

### `POST /api/agents/lead/followup`

Run the Follow-up Writer LangGraph agent. Executes 5 nodes:
`load_deal_history` → `retrieve_product_context` → `draft_email` → `self_review` → `route_by_confidence`

Self-review loop: if `review_score < 70` and `retry_count < 2`, the agent returns to
`draft_email` and tries again. Maximum 2 retries.

**Request body:**

```json
{
  "deal_id": "1dd1b8d6-3502-4637-af63-90afa0e052f1"
}
```

| Field | Type | Required |
|---|---|---|
| `deal_id` | string (UUID) | ✅ |

**Response `200 OK`:**

```json
{
  "draft":        "Dear Jane, following our conversation about the Revenyu CRM deployment for your 50-agent team...",
  "review_score": 82,
  "run_id":       "9397bbb8-5f2e-4c1a-b8e3-2d1a764223da"
}
```

`review_score` is the agent's self-assessed quality score (0–100). Scores below 70
triggered a retry. The returned draft is always the best version produced.

**Errors:**

| Code | Condition |
|---|---|
| `404` | `deal_id` not found in database |
| `422` | Missing or malformed `deal_id` |
| `500` | LangGraph execution failure |

**Example:**

```bash
curl -X POST http://localhost:8000/api/agents/lead/followup \
  -H "Content-Type: application/json" \
  -d '{"deal_id": "1dd1b8d6-3502-4637-af63-90afa0e052f1"}'
```

---

### `GET /api/agents/pipeline/report`

Run the Pipeline Reporter LangGraph agent. Executes 5 nodes:
`query_pipeline_data` → `compute_kpis` → `identify_bottlenecks` → `generate_digest` → `route_to_output`

KPIs are computed directly from SQLite — no LLM involved in the numbers.
The executive digest is LLM-written, based only on the computed KPIs.

**No request body.**

**Response `200 OK`:**

```json
{
  "kpis": {
    "conversion_rate":     0.325,
    "avg_deal_age":        14.2,
    "total_pipeline_value": 245000.0,
    "stage_distribution": {
      "new_lead":     5,
      "hot_lead":     3,
      "nurture":      8,
      "proposal":     2,
      "closed_won":   4,
      "closed_lost":  1,
      "disqualified": 2,
      "escalated":    1
    }
  },
  "bottlenecks": [
    "Lead qualification bottleneck: 8 leads in nurture stage",
    "Deals aging: average 14.2 days in pipeline"
  ],
  "digest": "The pipeline shows healthy volume at $245,000 with a 32.5% conversion rate, above the 30% target. However, the nurture stage is accumulating leads — 8 currently stalled — suggesting the follow-up cadence needs attention...",
  "run_id": "abc12345-6789-4def-a012-bcdef0123456"
}
```

`conversion_rate` is a float (0.0–1.0). Multiply by 100 for percentage display.
`avg_deal_age` is in days (float).
`total_pipeline_value` is the sum of all deal values in the database (float, USD).

**Errors:**

| Code | Condition |
|---|---|
| `500` | LangGraph execution failure or empty database |

**Example:**

```bash
curl http://localhost:8000/api/agents/pipeline/report
```

---

### `GET /api/agents/trace/{run_id}`

Retrieve the full LangGraph execution trace for any completed agent run.
Returns all node states, timing, and input/output JSON for debugging and auditing.

**Path parameter:**

| Parameter | Type | Description |
|---|---|---|
| `run_id` | string (UUID) | The `run_id` returned from any agent endpoint |

**Response `200 OK`:**

```json
{
  "run_id":      "1dd1b8d6-3502-4637-af63-90afa0e052f1",
  "agent_name":  "lead_classifier",
  "status":      "completed",
  "started_at":  "2026-05-11 21:59:03",
  "completed_at": "2026-05-11 21:59:09",
  "input_json":  "{\"company\": \"Acme Corp\", ...}",
  "output_json": "{\"stage\": \"hot_lead\", \"score\": 88, ...}",
  "nodes": [
    "classify_intent",
    "retrieve_context",
    "enrich_lead",
    "score_lead",
    "route_to_pipeline"
  ]
}
```

`agent_name` values: `lead_classifier` | `followup_writer` | `pipeline_reporter`

`status` values: `running` | `completed` | `failed`

**Errors:**

| Code | Condition |
|---|---|
| `404` | `run_id` not found in `agent_runs` table |

**Example:**

```bash
curl http://localhost:8000/api/agents/trace/1dd1b8d6-3502-4637-af63-90afa0e052f1
```

---

## MCP Server

### `GET /api/mcp/tools`

List all 10 tools exposed by the FastMCP server. Useful for debugging — Claude Desktop
and any MCP-compatible client discover tools via the SSE transport, not this endpoint.

**No request body.**

**Response `200 OK`:**

```json
{
  "tools": [
    {"name": "nexus_query_leads",     "description": "Query leads from the CRM database..."},
    {"name": "nexus_query_deals",     "description": "Query deals with optional filters..."},
    {"name": "nexus_get_deal_history","description": "Get full history for a specific deal..."},
    {"name": "nexus_update_deal_stage","description": "Update the stage of a deal..."},
    {"name": "nexus_search_knowledge","description": "Search the RAG knowledge base..."},
    {"name": "nexus_ingest_document", "description": "Ingest a document into the knowledge base..."},
    {"name": "nexus_draft_email",     "description": "Draft a follow-up email for a deal..."},
    {"name": "nexus_schedule_followup","description": "Run the follow-up writer agent..."},
    {"name": "nexus_pipeline_kpis",   "description": "Generate a full pipeline KPI report..."},
    {"name": "nexus_agent_runs",      "description": "Query recent agent run logs..."}
  ],
  "count": 10
}
```

**SSE transport (for Claude Desktop):**

```
GET /mcp/sse
```

This is the endpoint Claude Desktop connects to. It is not under `/api` — it is mounted
directly at `/mcp/sse` in the FastAPI app. Claude Desktop config:

```json
{
  "mcpServers": {
    "nexus-ai": {
      "url": "http://localhost:8000/mcp/sse"
    }
  }
}
```

---

## MCP Tool Reference

All 10 tools are callable by Claude Desktop via the MCP SSE transport.
The descriptions below match what Claude sees when it calls `list_tools`.

### Data Tools (fast, SQLite only, no LLM)

**`nexus_query_leads(stage="", limit=20)`**
Returns lead records from SQLite. Optionally filter by stage. Capped at 100. Ordered by `created_at DESC`.

**`nexus_query_deals(stage="", owner="", limit=20)`**
Returns deal records joined with `leads.company`. Filter by stage and/or owner.

**`nexus_get_deal_history(deal_id)`**
Returns `{"deal": {...}, "lead": {...}}`. Returns `{"error": "Deal not found"}` on missing ID.

**`nexus_pipeline_summary()`**
Fast snapshot: lead counts by stage, deal counts by stage, total deal value. No LLM. Use for instant checks. Use `nexus_pipeline_kpis` for the full report with digest.

**`nexus_agent_runs(agent_name="", status="", limit=10)`**
Returns truncated agent run logs (200-char previews). For full traces, use `GET /api/agents/trace/{run_id}`.

### Knowledge Tool (calls RAG pipeline)

**`nexus_search_knowledge(query, top_k=3)`**
Runs the full hybrid retrieval pipeline: embed → semantic search → BM25 → CrossEncoder rerank → LLM answer. Returns `{answer, sources, latency_ms}`.

### Action Tools (write to DB or invoke LangGraph)

**`nexus_update_deal_stage(deal_id, new_stage, owner="")`**
Validates `new_stage` against `LeadStage` enum first. Updates deal in SQLite. Returns `{success, deal_id, new_stage, message}`.

**`nexus_ingest_document(source, doc_type="auto")`**
Ingests a document into ChromaDB. Returns `{source, doc_type, chunk_count, duration_ms, errors}`.

**`nexus_schedule_followup(deal_id)`**
Runs the Follow-up Writer agent. Returns `{draft, review_score, run_id}`. Takes 5–15s.

**`nexus_pipeline_kpis()`**
Runs the full Pipeline Reporter agent. Returns `{kpis, bottlenecks, digest, run_id}`. Takes 10–20s. Use `nexus_pipeline_summary` for instant snapshots.

---

## Database Reference

### Lead stages

| Stage | Condition | Meaning |
|---|---|---|
| `new_lead` | Default | Just entered the system |
| `hot_lead` | score ≥ 80 | High intent, immediate follow-up |
| `nurture` | score 50–79 | Interested but not ready |
| `proposal` | Manual | Proposal sent |
| `closed_won` | Manual | Deal closed successfully |
| `closed_lost` | Manual | Deal lost |
| `disqualified` | score < 50 | Low fit or intent |
| `escalated` | Red flags | Needs human review |

### Tables

```
leads       — id, company, contact_name, contact_email, source, stage, score, timestamps
deals       — id, lead_id (FK), stage, value, owner, last_contact, timestamps
agent_runs  — id, agent_name, run_id (UNIQUE), input_json, output_json, status, timestamps
rag_queries — id, query_text, response_text, sources_json, latency_ms, model_used, created_at
```

---

## Error Responses

All errors follow FastAPI's default format:

```json
{"detail": "Error message here"}
```

Common HTTP status codes:

| Code | Meaning |
|---|---|
| `200` | Success |
| `404` | Resource not found (deal_id, run_id) |
| `422` | Validation error (missing required fields, wrong types) |
| `500` | Internal error (LLM failure, ChromaDB down, agent crash) |
| `501` | Not implemented (placeholder endpoints not yet built) |

---

*Nexus-AI API Contract — v1.0.0*
*Owner: Abdel Rahman M. El-Saied*
*GitHub: github.com/AbdelRahman-Madboly/Nexus-AI*