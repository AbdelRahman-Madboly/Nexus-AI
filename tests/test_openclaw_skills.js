/**
 * tests/test_openclaw_skills.js
 * ==============================
 * Integration test suite for Nexus OpenClaw Skills.
 *
 * These tests call the REAL Nexus FastAPI endpoints — no mocking.
 * Requirement: uvicorn api.main:app must be running on port 8000.
 *
 * Run:
 *   node tests/test_openclaw_skills.js
 *
 * Exit code 0 = all tests passed.
 * Exit code 1 = one or more tests failed.
 *
 * The suite covers the endpoints that the OpenClaw skills call:
 *   - Health        (all skills check connectivity before failing)
 *   - RAG query     (nexus-rag skill)
 *   - Lead classify (nexus-leads skill — classify sub-intent)
 *   - MCP tools     (verifies the backend the MCP tool tests validated)
 *   - Pipeline KPI  (nexus-pipeline skill)
 *
 * Test 2 (RAG) will return an empty-ish answer if no documents have been
 * ingested yet — the test checks the response SHAPE, not the content,
 * so it passes on a fresh database. Ingest a document first for a richer test:
 *   curl -X POST http://localhost:8000/api/rag/ingest \
 *        -H 'Content-Type: application/json' \
 *        -d '{"source": "https://projecx.io"}'
 */

import assert from 'assert';
import axios  from 'axios';

// ---------------------------------------------------------------------------
// Config — can be overridden via environment variable for CI
// ---------------------------------------------------------------------------
const BASE_URL   = process.env.NEXUS_API_URL || 'http://localhost:8000';
const API_TIMEOUT = 60_000;  // 60s — pipeline report needs extra time

const api = axios.create({
  baseURL:         BASE_URL,
  timeout:         API_TIMEOUT,
  // Do NOT throw on non-2xx — we want to inspect response codes in tests
  validateStatus:  () => true,
});

// ---------------------------------------------------------------------------
// Minimal test runner — uses only Node.js built-ins (no Jest, no Mocha)
// ---------------------------------------------------------------------------
let passed = 0;
let failed = 0;

async function test(name, fn) {
  try {
    await fn();
    console.log(`✅ ${name}`);
    passed++;
  } catch (err) {
    console.error(`❌ ${name}`);
    console.error(`   ${err.message}`);
    // Print the actual vs expected for assertion errors
    if (err.actual !== undefined) {
      console.error(`   actual:   ${JSON.stringify(err.actual)}`);
      console.error(`   expected: ${JSON.stringify(err.expected)}`);
    }
    failed++;
    process.exitCode = 1;
  }
}

// ---------------------------------------------------------------------------
// Helper: assert HTTP status is in expected list
// ---------------------------------------------------------------------------
function assertStatus(res, ...expected) {
  assert(
    expected.includes(res.status),
    `Expected HTTP ${expected.join(' or ')} but got ${res.status}. ` +
    `Body: ${JSON.stringify(res.data).slice(0, 200)}`
  );
}

// ===========================================================================
// TEST 1: Health endpoint
// Verifies the server is up and returns a valid status string.
// 'degraded' is acceptable — it means the server is up but a dependency
// (Ollama, ChromaDB) is not. Skills should still function in degraded state
// (e.g., if Ollama is down but LLM_BACKEND=gemini, RAG still works).
// ===========================================================================
await test('Health endpoint returns ok or degraded', async () => {
  const res = await api.get('/api/health');
  assertStatus(res, 200);
  assert(
    ['ok', 'degraded'].includes(res.data.status),
    `Expected status to be 'ok' or 'degraded', got: ${res.data.status}`
  );
  // Verify the components block is present — skills depend on these
  assert(typeof res.data.components === 'object', 'Expected components object');
  assert('database' in res.data.components,        'Expected database component');
});

// ===========================================================================
// TEST 2: RAG query returns an answer
// Tests the nexus-rag skill's backend endpoint.
// The test verifies SHAPE (answer is a string), not CONTENT.
// This means it passes even on a fresh database with no documents ingested —
// the RAG retriever returns a "not found" message which is still a string.
// ===========================================================================
await test('RAG query returns answer string and sources array', async () => {
  const res = await api.post('/api/rag/query', {
    query:  'What is Nexus-AI?',
    top_k:  1,
    stream: false,
  });
  assertStatus(res, 200);
  assert(typeof res.data.answer  === 'string',  'Expected answer to be a string');
  assert(Array.isArray(res.data.sources),        'Expected sources to be an array');
  assert(typeof res.data.latency_ms === 'number', 'Expected latency_ms to be a number');
  assert(res.data.latency_ms >= 0,               'Expected latency_ms >= 0');
});

// ===========================================================================
// TEST 3: Lead classify returns a valid stage and score
// Tests the nexus-leads skill's classify sub-intent backend.
// Uses a generic test lead — the agent will classify it, likely as 'nurture'
// (50–79 score for a vague CRM request with no urgency signals).
// ===========================================================================
await test('Lead classify returns valid stage and numeric score', async () => {
  const res = await api.post('/api/agents/lead/classify', {
    company:       'Test Corp',
    contact_name:  'Test User',
    contact_email: 'test@example.com',
    source:        'telegram',
    message:       'We are evaluating AI CRM tools for our sales team of 50 people.',
  });
  assertStatus(res, 200);

  const VALID_STAGES = [
    'new_lead', 'hot_lead', 'nurture', 'proposal',
    'closed_won', 'closed_lost', 'disqualified', 'escalated',
  ];
  assert(
    VALID_STAGES.includes(res.data.stage),
    `Expected a valid LeadStage, got: ${res.data.stage}`
  );
  assert(typeof res.data.score  === 'number', 'Expected score to be a number');
  assert(res.data.score >= 0 && res.data.score <= 100, 'Expected score between 0 and 100');
  assert(typeof res.data.run_id === 'string',  'Expected run_id to be a string');
  assert(res.data.run_id.length > 0,           'Expected non-empty run_id');
});

// ===========================================================================
// TEST 4: MCP tools endpoint returns exactly 10 tools
// All 10 tools were verified in test_mcp.py — this test checks the HTTP
// endpoint that the MCP router exposes, ensuring nothing was broken when
// the SSE transport was mounted in main.py.
// ===========================================================================
await test('MCP tools endpoint returns exactly 10 tools', async () => {
  const res = await api.get('/api/mcp/tools');
  assertStatus(res, 200);
  assert(typeof res.data.count  === 'number', 'Expected count to be a number');
  assert(Array.isArray(res.data.tools),       'Expected tools to be an array');
  assert(
    res.data.count === 10,
    `Expected 10 MCP tools, got: ${res.data.count}`
  );
  assert(
    res.data.tools.length === 10,
    `Expected tools array length 10, got: ${res.data.tools.length}`
  );
  // Verify each tool has name and description fields
  for (const tool of res.data.tools) {
    assert(typeof tool.name        === 'string', `Tool missing name: ${JSON.stringify(tool)}`);
    assert(typeof tool.description === 'string', `Tool missing description: ${JSON.stringify(tool)}`);
  }
});

// ===========================================================================
// TEST 5: Pipeline report returns valid KPI structure
// This is the slowest test (~5–25 seconds) because the reporter makes a real
// LLM call inside LangGraph. The test verifies structure, not KPI values —
// values depend on what's in the database.
// ===========================================================================
await test('Pipeline report returns kpis object with required fields', async () => {
  const res = await api.get('/api/agents/pipeline/report');
  assertStatus(res, 200);

  // Top-level structure
  assert(typeof res.data.kpis  === 'object', 'Expected kpis to be an object');
  assert(Array.isArray(res.data.bottlenecks), 'Expected bottlenecks to be an array');
  assert(typeof res.data.digest === 'string', 'Expected digest to be a string');
  assert(typeof res.data.run_id === 'string', 'Expected run_id to be a string');

  // KPI sub-fields — all four must be present even if the DB is empty (value = 0)
  const kpis = res.data.kpis;
  assert('conversion_rate'      in kpis, 'Expected conversion_rate in kpis');
  assert('avg_deal_age'         in kpis, 'Expected avg_deal_age in kpis');
  assert('stage_distribution'   in kpis, 'Expected stage_distribution in kpis');
  assert('total_pipeline_value' in kpis, 'Expected total_pipeline_value in kpis');

  // Types
  assert(typeof kpis.conversion_rate      === 'number', 'conversion_rate must be a number');
  assert(typeof kpis.total_pipeline_value === 'number', 'total_pipeline_value must be a number');
  assert(typeof kpis.stage_distribution   === 'object', 'stage_distribution must be an object');
});

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed + failed} tests — ${passed} passed, ${failed} failed`);
if (failed > 0) {
  console.error('\nRun "uvicorn api.main:app --reload" and try again.');
}