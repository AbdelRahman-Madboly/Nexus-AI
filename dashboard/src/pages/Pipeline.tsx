import { useState, useEffect, useCallback } from 'react';
import { nexusApi, ReportResponse, KpiData } from '../api/nexusApi';

// ---------------------------------------------------------------------------
// Stage colours
// ---------------------------------------------------------------------------

const STAGE_COLORS: Record<string, string> = {
  new_lead:     'bg-gray-400',
  hot_lead:     'bg-red-500',
  nurture:      'bg-yellow-500',
  proposal:     'bg-blue-500',
  closed_won:   'bg-emerald-500',
  closed_lost:  'bg-gray-600',
  disqualified: 'bg-gray-500',
  escalated:    'bg-orange-500',
};

// Ordered stage list for display
const STAGE_ORDER = [
  'new_lead', 'hot_lead', 'nurture', 'proposal',
  'closed_won', 'closed_lost', 'disqualified', 'escalated',
];

// ---------------------------------------------------------------------------
// KPI card
// ---------------------------------------------------------------------------

interface KpiCardProps {
  label: string;
  value: string;
  sub?:  string;
  color: 'green' | 'orange' | 'red' | 'blue';
}

const COLOR_MAP: Record<KpiCardProps['color'], string> = {
  green:  'text-emerald-500 border-emerald-200 dark:border-emerald-800',
  orange: 'text-amber-500 border-amber-200 dark:border-amber-800',
  red:    'text-red-500 border-red-200 dark:border-red-800',
  blue:   'text-brand-500 border-brand-200 dark:border-blue-800',
};

function KpiCard({ label, value, sub, color }: KpiCardProps) {
  return (
    <div className={`rounded-2xl border bg-white dark:bg-gray-900 p-5 ${COLOR_MAP[color]}`}>
      <p className="text-xs text-gray-400 uppercase tracking-wider mb-2">{label}</p>
      <p className={`text-3xl font-bold ${COLOR_MAP[color].split(' ')[0]}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

function KpiCardSkeleton() {
  return (
    <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5 animate-pulse">
      <div className="h-3 w-20 bg-gray-200 dark:bg-gray-700 rounded mb-3" />
      <div className="h-8 w-24 bg-gray-200 dark:bg-gray-700 rounded" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// KPI colour rules
// ---------------------------------------------------------------------------

function conversionColor(rate: number): KpiCardProps['color'] {
  if (rate > 30) return 'green';
  if (rate > 15) return 'orange';
  return 'red';
}

function ageColor(days: number): KpiCardProps['color'] {
  if (days < 14) return 'green';
  if (days <= 30) return 'orange';
  return 'red';
}

function bottleneckColor(count: number): KpiCardProps['color'] {
  if (count === 0) return 'green';
  if (count <= 2) return 'orange';
  return 'red';
}

// ---------------------------------------------------------------------------
// Stage bar
// ---------------------------------------------------------------------------

function StageBar({ stage, count, total }: { stage: string; count: number; total: number }) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  const color = STAGE_COLORS[stage] ?? 'bg-gray-400';

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs font-mono text-gray-500 dark:text-gray-400 w-28 flex-shrink-0 truncate">
        {stage}
      </span>
      <div className="flex-1 h-2.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
        <div
          className={`h-full rounded-full ${color} transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-500 dark:text-gray-400 w-6 text-right flex-shrink-0">
        {count}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pipeline page
// ---------------------------------------------------------------------------

export default function Pipeline() {
  const [report,      setReport]      = useState<ReportResponse | null>(null);
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState<string | null>(null);
  const [lastGenAt,   setLastGenAt]   = useState<Date | null>(null);
  const [isInitial,   setIsInitial]   = useState(true);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await nexusApi.getPipelineReport();
      setReport(data);
      setLastGenAt(new Date());
    } catch (err) {
      let msg = 'Failed to generate report.';
      if (err instanceof Response) {
        try { const j = await err.json(); msg = j.detail || msg; } catch { /* noop */ }
      } else if (err instanceof DOMException && err.name === 'AbortError') {
        msg = 'Request timed out (90s). The pipeline reporter is still running.';
      }
      setError(msg);
    } finally {
      setLoading(false);
      setIsInitial(false);
    }
  }, []);

  // Auto-fetch on mount
  useEffect(() => { fetchReport(); }, [fetchReport]);

  const kpis: KpiData | undefined = report?.kpis;
  const convRate  = (kpis?.conversion_rate      ?? 0);
  const avgAge    = (kpis?.avg_deal_age          ?? 0);
  const pipeVal   = (kpis?.total_pipeline_value  ?? 0);
  const stageDist = kpis?.stage_distribution ?? {};
  const totalLeads = Object.values(stageDist).reduce((s, n) => s + n, 0);
  const bottlenecks = report?.bottlenecks ?? [];

  // Check if DB is likely empty
  const isEmpty = !loading && !isInitial && report && totalLeads === 0;

  return (
    <div className="flex flex-col h-full bg-gray-50 dark:bg-gray-950">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <div>
          <h1 className="font-semibold text-gray-900 dark:text-white text-lg">Pipeline</h1>
          <p className="text-xs text-gray-400">
            {lastGenAt
              ? `Last generated: ${lastGenAt.toLocaleTimeString()}`
              : 'Live KPIs + LangGraph reporter'}
          </p>
        </div>
        <button
          onClick={fetchReport}
          disabled={loading}
          className="
            flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg
            bg-brand-600 hover:bg-brand-700 text-white
            disabled:opacity-50 disabled:cursor-not-allowed transition-colors
          "
        >
          {loading && (
            <span className="h-4 w-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
          )}
          Generate Report
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-8 scrollbar-thin max-w-5xl mx-auto w-full">

        {/* Error */}
        {error && (
          <div className="rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-4 py-3 text-sm text-red-600 dark:text-red-400 flex items-center justify-between gap-4">
            <span>{error}</span>
            <button
              onClick={fetchReport}
              className="text-xs underline flex-shrink-0"
            >
              Retry
            </button>
          </div>
        )}

        {/* Empty state */}
        {isEmpty && (
          <div className="text-center py-16 text-gray-400">
            <p className="text-3xl mb-3">📭</p>
            <p className="font-medium text-gray-500">No pipeline data yet.</p>
            <p className="text-sm mt-1">Add leads to get started.</p>
          </div>
        )}

        {/* ── KPI Cards ─────────────────────────────────── */}
        <section>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4">KPIs</h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {(loading && isInitial) ? (
              [0, 1, 2, 3].map(i => <KpiCardSkeleton key={i} />)
            ) : report ? (
              <>
                <KpiCard
                  label="Conversion"
                  value={`${convRate.toFixed(1)}%`}
                  sub="closed_won / (won + lost)"
                  color={conversionColor(convRate)}
                />
                <KpiCard
                  label="Avg Deal Age"
                  value={`${avgAge.toFixed(1)}d`}
                  sub="days in pipeline"
                  color={ageColor(avgAge)}
                />
                <KpiCard
                  label="Pipeline"
                  value={`$${pipeVal.toLocaleString()}`}
                  sub="total deal value"
                  color="blue"
                />
                <KpiCard
                  label="Bottlenecks"
                  value={String(bottlenecks.length)}
                  sub={bottlenecks.length === 0 ? 'all clear' : 'issues found'}
                  color={bottleneckColor(bottlenecks.length)}
                />
              </>
            ) : null}
          </div>
        </section>

        {/* ── Stage Distribution ─────────────────────────── */}
        {!isEmpty && report && (
          <section>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4">
              Stage Distribution
            </h2>
            <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5 space-y-3">
              {STAGE_ORDER.map(stage => {
                const count = stageDist[stage] ?? 0;
                if (count === 0) return null;
                return (
                  <StageBar key={stage} stage={stage} count={count} total={totalLeads} />
                );
              })}
              {/* Any stages not in the canonical order */}
              {Object.entries(stageDist)
                .filter(([s]) => !STAGE_ORDER.includes(s))
                .map(([stage, count]) => (
                  <StageBar key={stage} stage={stage} count={count} total={totalLeads} />
                ))}
            </div>
          </section>
        )}

        {/* ── Bottlenecks ───────────────────────────────── */}
        {!isEmpty && report && bottlenecks.length > 0 && (
          <section>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4">
              Bottlenecks
            </h2>
            <div className="rounded-2xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-5 space-y-2">
              {bottlenecks.map((b, i) => (
                <div key={i} className="flex items-start gap-2 text-sm text-amber-700 dark:text-amber-400">
                  <span className="flex-shrink-0 mt-0.5">⚠</span>
                  <span>{b}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ── Executive Digest ──────────────────────────── */}
        {!isEmpty && report?.digest && (
          <section>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4">
              Executive Digest
            </h2>
            <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5">
              <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-wrap">
                {report.digest}
              </p>
              <p className="mt-4 text-xs text-gray-400 font-mono">
                Run ID: {report.run_id}
                {lastGenAt && ` · Generated at ${lastGenAt.toLocaleTimeString()}`}
              </p>
            </div>
          </section>
        )}

      </div>
    </div>
  );
}