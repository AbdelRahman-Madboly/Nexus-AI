// nexusApi.ts
// =============================================================
// ONLY file in the dashboard that makes HTTP calls to the FastAPI.
// All page components import from here — never fetch() directly in pages.
// =============================================================

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HealthComponent {
  status: 'ok' | 'degraded';
  detail: string | null;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  components: {
    database:    HealthComponent;
    ollama:      HealthComponent;
    llm_backend: HealthComponent;
  };
}

export interface IngestRequest {
  source:    string;
  doc_type?: string;
  metadata?: Record<string, string>;
}

export interface IngestResponse {
  source:      string;
  doc_type:    string;
  chunk_count: number;
  duration_ms: number;
}

export interface RagSource {
  id:       string;
  text:     string;
  metadata: Record<string, unknown>;
  score:    number;
}

export interface RagQueryRequest {
  query:   string;
  top_k?:  number;
  stream?: boolean;
}

export interface RagQueryResponse {
  answer:     string;
  sources:    RagSource[];
  latency_ms: number;
}

export interface LeadClassifyRequest {
  company:        string;
  contact_name:   string;
  contact_email?: string;
  source:         string;
  message:        string;
}

export interface LeadClassifyResponse {
  stage:     string;
  score:     number;
  reasoning: string;
  run_id:    string;
}

export interface FollowupRequest {
  deal_id: string;
}

export interface FollowupResponse {
  draft:        string;
  review_score: number;
  run_id:       string;
}

export interface KpiData {
  conversion_rate:      number;
  avg_deal_age:         number;
  stage_distribution:   Record<string, number>;
  total_pipeline_value: number;
}

export interface ReportResponse {
  kpis:        KpiData;
  bottlenecks: string[];
  digest:      string;
  run_id:      string;
}

export interface AgentRun {
  id:           string;
  agent_name:   string;
  run_id:       string;
  input_json:   string | null;
  output_json:  string | null;
  status:       string;
  started_at:   string;
  completed_at: string | null;
}

export interface McpTool {
  name:        string;
  description: string;
}

export interface McpToolsResponse {
  tools: McpTool[];
  count: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const BASE = '/api';

/** Wrap fetch with a timeout via AbortController */
async function fetchWithTimeout(
  url: string,
  options: RequestInit,
  timeoutMs: number
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    return res;
  } finally {
    clearTimeout(timer);
  }
}

async function get<T>(path: string, timeoutMs = 30_000): Promise<T> {
  const res = await fetchWithTimeout(`${BASE}${path}`, {}, timeoutMs);
  if (!res.ok) throw res;
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown, timeoutMs = 30_000): Promise<T> {
  const res = await fetchWithTimeout(
    `${BASE}${path}`,
    {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    },
    timeoutMs
  );
  if (!res.ok) throw res;
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

export const nexusApi = {
  /** Health check — fast, no timeout extension needed */
  getHealth(): Promise<HealthResponse> {
    return get<HealthResponse>('/health');
  },

  /** Ingest a document (URL, file path, or raw text) into ChromaDB */
  ingestDocument(req: IngestRequest): Promise<IngestResponse> {
    // Ingest can be slow for large URLs (embed + ChromaDB) — 120s
    return post<IngestResponse>('/rag/ingest', req, 120_000);
  },

  /** Hybrid RAG query — semantic + BM25 + CrossEncoder + LLM answer */
  queryKnowledge(req: RagQueryRequest): Promise<RagQueryResponse> {
    // CrossEncoder + LLM: up to 60s on first cold start
    return post<RagQueryResponse>('/rag/query', req, 60_000);
  },

  /** Classify a lead through the 5-node LangGraph classifier */
  classifyLead(req: LeadClassifyRequest): Promise<LeadClassifyResponse> {
    // LangGraph agent + 3 LLM calls: up to 90s
    return post<LeadClassifyResponse>('/agents/lead/classify', req, 90_000);
  },

  /** Run the follow-up writer agent for a given deal_id */
  writeFollowup(req: FollowupRequest): Promise<FollowupResponse> {
    // Self-review loop (up to 3 LLM pairs): 90s
    return post<FollowupResponse>('/agents/lead/followup', req, 90_000);
  },

  /** Run the pipeline reporter agent — KPIs + bottlenecks + digest */
  getPipelineReport(): Promise<ReportResponse> {
    // Reporter: 4-section KPI compute + LLM digest: up to 90s
    return get<ReportResponse>('/agents/pipeline/report', 90_000);
  },

  /** Fetch a full agent_runs row by run_id */
  getAgentTrace(runId: string): Promise<AgentRun> {
    return get<AgentRun>(`/agents/trace/${encodeURIComponent(runId)}`);
  },

  /** List all 10 MCP tool definitions */
  listMcpTools(): Promise<McpToolsResponse> {
    return get<McpToolsResponse>('/mcp/tools');
  },
};