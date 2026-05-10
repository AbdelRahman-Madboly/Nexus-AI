import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { nexusApi, AgentRun } from '../api/nexusApi';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AGENT_NODES: Record<string, string[]> = {
  lead_classifier: [
    'classify_intent',
    'retrieve_context',
    'enrich_lead',
    'score_lead',
    'route_to_pipeline',
  ],
  followup_writer: [
    'load_deal_history',
    'retrieve_product_context',
    'draft_email',
    'self_review',
    'route_by_confidence',
  ],
  pipeline_reporter: [
    'query_pipeline_data',
    'compute_kpis',
    'identify_bottlenecks',
    'generate_digest',
    'route_to_output',
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function durationSeconds(run: AgentRun): number | null {
  if (!run.completed_at) return null;
  const start = new Date(run.started_at).getTime();
  const end   = new Date(run.completed_at).getTime();
  return Math.round((end - start) / 1000);
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function nodeIcon(status: string): string {
  if (status === 'completed') return '✅';
  if (status === 'failed')    return '❌';
  return '⏳';
}

// ---------------------------------------------------------------------------
// JSON pretty-printer with simple colour via CSS classes
// ---------------------------------------------------------------------------

function JsonBlock({ data }: { data: unknown }) {
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(data, null, 2);

  function copy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  // Syntax colouring: keys in blue, strings in green, numbers in orange
  const highlighted = text
    .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(?=\s*:))/g, '<span class="text-blue-400">$1</span>')
    .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*")(?!\s*:)/g, '<span class="text-emerald-400">$1</span>')
    .replace(/\b(-?\d+(\.\d+)?)\b/g, '<span class="text-orange-400">$1</span>');

  return (
    <div className="relative rounded-xl bg-gray-950 border border-gray-700 overflow-hidden">
      <button
        onClick={copy}
        className="absolute top-2 right-2 text-xs text-gray-400 hover:text-white px-2 py-1 rounded bg-gray-800 transition-colors"
      >
        {copied ? '✅ Copied' : 'Copy'}
      </button>
      <pre
        className="p-4 text-xs font-mono text-gray-300 overflow-x-auto scrollbar-thin"
        dangerouslySetInnerHTML={{ __html: highlighted }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    completed: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400',
    failed:    'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400',
    running:   'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400 animate-pulse',
  };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${styles[status] ?? styles['running']}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Node timeline
// ---------------------------------------------------------------------------

function NodeTimeline({ agentName, status }: { agentName: string; status: string }) {
  const nodes = AGENT_NODES[agentName] ?? [];
  if (nodes.length === 0) return null;

  return (
    <div className="space-y-2">
      {nodes.map((node, i) => (
        <div key={node} className="flex items-center gap-3">
          {/* Step number */}
          <span className="text-xs font-mono text-gray-400 w-4 text-right flex-shrink-0">
            {i + 1}
          </span>
          {/* Line connector */}
          <div className="flex flex-col items-center gap-0.5 flex-shrink-0">
            <div className="h-2 w-px bg-gray-200 dark:bg-gray-700" />
            <div className={`h-2.5 w-2.5 rounded-full flex-shrink-0 ${
              status === 'completed' ? 'bg-emerald-400' :
              status === 'failed' && i === nodes.length - 1 ? 'bg-red-400' :
              status === 'running' && i === nodes.length - 1 ? 'bg-amber-400 animate-pulse' :
              'bg-emerald-400'
            }`} />
            {i < nodes.length - 1 && <div className="h-2 w-px bg-gray-200 dark:bg-gray-700" />}
          </div>
          {/* Node name */}
          <span className="text-sm font-mono text-gray-700 dark:text-gray-300 flex-1">
            {node}
          </span>
          {/* Icon */}
          <span className="text-sm flex-shrink-0">{nodeIcon(status)}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AgentTracer page
// ---------------------------------------------------------------------------

export default function AgentTracer() {
  const [searchParams]          = useSearchParams();
  const [runId, setRunId]       = useState(searchParams.get('run_id') ?? '');
  const [inputVal, setInputVal] = useState(searchParams.get('run_id') ?? '');
  const [trace, setTrace]       = useState<AgentRun | null>(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const inputRef                = useRef<HTMLInputElement>(null);

  const fetchTrace = useCallback(async (id: string) => {
    const trimmed = id.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    setTrace(null);
    try {
      const data = await nexusApi.getAgentTrace(trimmed);
      setTrace(data);
    } catch (err) {
      if (err instanceof Response && err.status === 404) {
        setError(`No trace found for run_id: ${trimmed}`);
      } else {
        setError('Failed to fetch trace. Is the API running?');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Auto-fetch from URL param on mount
  useEffect(() => {
    const id = searchParams.get('run_id');
    if (id) fetchTrace(id);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleTrace() {
    setRunId(inputVal);
    fetchTrace(inputVal);
  }

  function handleClear() {
    setRunId('');
    setInputVal('');
    setTrace(null);
    setError(null);
    inputRef.current?.focus();
  }

  // Parse JSON fields safely
  const inputData  = trace?.input_json  ? JSON.parse(trace.input_json)  : null;
  const outputData = trace?.output_json ? JSON.parse(trace.output_json) : null;
  const duration   = trace ? durationSeconds(trace) : null;

  return (
    <div className="flex flex-col h-full bg-gray-50 dark:bg-gray-950">
      {/* Header */}
      <header className="px-6 py-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <h1 className="font-semibold text-gray-900 dark:text-white text-lg">Agent Tracer</h1>
        <p className="text-xs text-gray-400">LangGraph run inspector · paste a run_id to visualise</p>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6 scrollbar-thin max-w-4xl mx-auto w-full">

        {/* run_id input */}
        <div className="flex gap-3">
          <input
            ref={inputRef}
            type="text"
            value={inputVal}
            onChange={e => setInputVal(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleTrace()}
            placeholder="Paste run_id here…"
            className="
              flex-1 rounded-xl border border-gray-300 dark:border-gray-600
              bg-white dark:bg-gray-800 px-4 py-2.5 text-sm font-mono
              text-gray-900 dark:text-white placeholder-gray-400
              focus:outline-none focus:ring-2 focus:ring-brand-500
            "
          />
          <button
            onClick={handleTrace}
            disabled={loading || !inputVal.trim()}
            className="
              px-5 py-2.5 rounded-xl text-sm font-medium
              bg-brand-600 hover:bg-brand-700 text-white
              disabled:opacity-40 disabled:cursor-not-allowed transition-colors
            "
          >
            {loading ? (
              <span className="h-4 w-4 border-2 border-white/40 border-t-white rounded-full animate-spin block" />
            ) : 'Trace'}
          </button>
          <button
            onClick={handleClear}
            className="px-5 py-2.5 rounded-xl text-sm font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            Clear
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        {/* Trace result */}
        {trace && (
          <div className="space-y-6">

            {/* Summary row */}
            <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5">
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <div>
                  <p className="text-xs text-gray-400 mb-1">Agent</p>
                  <p className="text-sm font-semibold text-gray-900 dark:text-white font-mono">
                    {trace.agent_name}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">Status</p>
                  <StatusBadge status={trace.status} />
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">Started</p>
                  <p className="text-sm text-gray-700 dark:text-gray-300">{formatTime(trace.started_at)}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">Duration</p>
                  <p className="text-sm text-gray-700 dark:text-gray-300">
                    {duration !== null ? `${duration}s` : trace.status === 'running' ? '⏳ running' : '—'}
                  </p>
                </div>
              </div>
            </div>

            {/* Node timeline */}
            <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4 uppercase tracking-wider text-xs">
                Node Timeline
              </h2>
              <NodeTimeline agentName={trace.agent_name} status={trace.status} />
            </div>

            {/* Input */}
            <div className="space-y-2">
              <h2 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Input
              </h2>
              {inputData ? <JsonBlock data={inputData} /> : (
                <p className="text-sm text-gray-400">—</p>
              )}
            </div>

            {/* Output */}
            <div className="space-y-2">
              <h2 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Output
              </h2>
              {outputData ? <JsonBlock data={outputData} /> : (
                <p className="text-sm text-gray-400">
                  {trace.status === 'running' ? 'Running…' : '—'}
                </p>
              )}
            </div>

          </div>
        )}
      </div>
    </div>
  );
}