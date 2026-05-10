import { useState, useRef, useEffect, KeyboardEvent } from 'react';
import { nexusApi, RagSource, IngestRequest } from '../api/nexusApi';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Message {
  role:       'user' | 'assistant';
  content:    string;
  latencyMs?: number;
  sources?:   RagSource[];
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SourceCard({ source, index }: { source: RagSource; index: number }) {
  const pct = Math.round(source.score * 100);
  const srcLabel =
    (source.metadata?.source as string | undefined) ||
    source.id.slice(0, 20) + '…';
  const preview = source.text.length > 150 ? source.text.slice(0, 150) + '…' : source.text;

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-3 text-sm space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-gray-500 dark:text-gray-400 text-xs">
          [{index + 1}] {srcLabel}
        </span>
        <span className="text-xs text-gray-400">{pct}%</span>
      </div>
      {/* Score bar */}
      <div className="h-1.5 rounded-full bg-gray-100 dark:bg-gray-700 overflow-hidden">
        <div
          className="h-full rounded-full bg-brand-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-gray-600 dark:text-gray-300 leading-relaxed">{preview}</p>
    </div>
  );
}

function TypingDots() {
  return (
    <div className="flex gap-1 items-center py-1">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="h-2 w-2 rounded-full bg-gray-400 dark:bg-gray-500 animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ingest Modal
// ---------------------------------------------------------------------------

interface IngestModalProps {
  onClose: () => void;
}

function IngestModal({ onClose }: IngestModalProps) {
  const [source, setSource]   = useState('');
  const [status, setStatus]   = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [result, setResult]   = useState('');

  async function handleIngest() {
    if (!source.trim()) return;
    setStatus('loading');
    setResult('');
    try {
      const req: IngestRequest = { source: source.trim() };
      const res = await nexusApi.ingestDocument(req);
      setResult(`✅ ${res.chunk_count} chunks ingested (${res.duration_ms.toLocaleString()}ms)`);
      setStatus('success');
    } catch (err) {
      let msg = 'Ingest failed';
      if (err instanceof Response) {
        try { const j = await err.json(); msg = j.detail || msg; } catch { /* noop */ }
      }
      setResult(msg);
      setStatus('error');
    }
  }

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-md rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 p-6 shadow-2xl space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-gray-900 dark:text-white text-lg">Ingest Document</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 text-xl leading-none"
          >
            ×
          </button>
        </div>

        <p className="text-sm text-gray-500 dark:text-gray-400">
          Enter a URL, file path, or paste raw text to ingest into the knowledge base.
        </p>

        <input
          type="text"
          value={source}
          onChange={e => setSource(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleIngest()}
          placeholder="https://projecx.io or /path/to/file.pdf"
          className="
            w-full rounded-lg border border-gray-300 dark:border-gray-600
            bg-white dark:bg-gray-800 px-3 py-2 text-sm
            text-gray-900 dark:text-white placeholder-gray-400
            focus:outline-none focus:ring-2 focus:ring-brand-500
          "
        />

        {result && (
          <p className={`text-sm ${status === 'error' ? 'text-red-500' : 'text-emerald-500'}`}>
            {result}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
          >
            Close
          </button>
          <button
            onClick={handleIngest}
            disabled={status === 'loading' || !source.trim()}
            className="
              px-4 py-2 text-sm rounded-lg font-medium
              bg-brand-600 hover:bg-brand-700 text-white
              disabled:opacity-50 disabled:cursor-not-allowed transition-colors
              flex items-center gap-2
            "
          >
            {status === 'loading' && (
              <span className="h-4 w-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            )}
            Ingest
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RagChat page
// ---------------------------------------------------------------------------

export default function RagChat() {
  const [messages,    setMessages]    = useState<Message[]>([]);
  const [input,       setInput]       = useState('');
  const [loading,     setLoading]     = useState(false);
  const [sources,     setSources]     = useState<RagSource[]>([]);
  const [showIngest,  setShowIngest]  = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef  = useRef<HTMLInputElement>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  async function sendMessage() {
    const q = input.trim();
    if (!q || loading) return;

    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: q }]);
    setLoading(true);

    try {
      const res = await nexusApi.queryKnowledge({ query: q, top_k: 3 });
      setMessages(prev => [
        ...prev,
        {
          role:      'assistant',
          content:   res.answer,
          latencyMs: res.latency_ms,
          sources:   res.sources,
        },
      ]);
      setSources(res.sources ?? []);
    } catch {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: '⚠️ Failed to reach the knowledge base. Is the API running?' },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-50 dark:bg-gray-950">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <div>
          <h1 className="font-semibold text-gray-900 dark:text-white text-lg">Knowledge Base</h1>
          <p className="text-xs text-gray-400">Hybrid RAG · ChromaDB + BM25 + CrossEncoder</p>
        </div>
        <button
          onClick={() => setShowIngest(true)}
          className="
            px-4 py-2 text-sm font-medium rounded-lg
            bg-brand-600 hover:bg-brand-700 text-white transition-colors
          "
        >
          + Ingest
        </button>
      </header>

      {/* Split panel */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── Chat panel (left) ─────────────────────────── */}
        <div className="flex flex-col flex-1 min-w-0">
          {/* Message history */}
          <div className="flex-1 overflow-y-auto px-6 py-6 space-y-5 scrollbar-thin">
            {messages.length === 0 && !loading && (
              <div className="flex flex-col items-center justify-center h-full text-center text-gray-400 select-none">
                <p className="text-3xl mb-3">🔍</p>
                <p className="text-base font-medium text-gray-500 dark:text-gray-400">
                  Ask anything about Projecx, Revenyu, or Bandora
                </p>
                <p className="text-sm mt-1 text-gray-400">
                  Ingest a document first if the knowledge base is empty.
                </p>
              </div>
            )}

            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`
                    max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed
                    ${msg.role === 'user'
                      ? 'bg-brand-600 text-white rounded-br-sm'
                      : 'bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 border border-gray-200 dark:border-gray-700 rounded-bl-sm'
                    }
                  `}
                >
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                  {msg.latencyMs !== undefined && (
                    <p className="mt-1.5 text-xs opacity-60">⚡ {(msg.latencyMs / 1000).toFixed(1)}s</p>
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl rounded-bl-sm px-4 py-3">
                  <TypingDots />
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* Input bar */}
          <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
            <div className="flex gap-3">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask a question…"
                disabled={loading}
                className="
                  flex-1 rounded-xl border border-gray-300 dark:border-gray-600
                  bg-gray-50 dark:bg-gray-800 px-4 py-2.5 text-sm
                  text-gray-900 dark:text-white placeholder-gray-400
                  focus:outline-none focus:ring-2 focus:ring-brand-500
                  disabled:opacity-50
                "
              />
              <button
                onClick={sendMessage}
                disabled={loading || !input.trim()}
                className="
                  px-5 py-2.5 rounded-xl font-medium text-sm
                  bg-brand-600 hover:bg-brand-700 text-white
                  disabled:opacity-40 disabled:cursor-not-allowed
                  transition-colors
                "
              >
                Ask
              </button>
            </div>
          </div>
        </div>

        {/* ── Sources panel (right) ──────────────────────── */}
        <div className="w-72 flex-shrink-0 border-l border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 flex flex-col">
          <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-800">
            <h2 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              Sources
            </h2>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-3 scrollbar-thin">
            {sources.length === 0 ? (
              <p className="text-sm text-gray-400 dark:text-gray-500 text-center mt-8">
                Ask a question to see sources
              </p>
            ) : (
              sources.map((src, i) => <SourceCard key={src.id} source={src} index={i} />)
            )}
          </div>
        </div>
      </div>

      {/* Ingest modal */}
      {showIngest && <IngestModal onClose={() => setShowIngest(false)} />}
    </div>
  );
}