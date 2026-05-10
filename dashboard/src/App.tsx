import { useState, useEffect, useCallback } from 'react';
import { Routes, Route, NavLink, useLocation } from 'react-router-dom';
import { nexusApi, HealthResponse } from './api/nexusApi';
import RagChat    from './pages/RagChat';
import AgentTracer from './pages/AgentTracer';
import Pipeline   from './pages/Pipeline';

// ---------------------------------------------------------------------------
// Icons (inline SVG — no icon library dependency)
// ---------------------------------------------------------------------------

function IconSearch() {
  return (
    <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
      <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
    </svg>
  );
}

function IconBot() {
  return (
    <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
      <rect x="3" y="11" width="18" height="10" rx="2"/>
      <path d="M12 11V7m-4 0a4 4 0 0 1 8 0"/>
      <circle cx="9" cy="16" r="1" fill="currentColor"/>
      <circle cx="15" cy="16" r="1" fill="currentColor"/>
    </svg>
  );
}

function IconChart() {
  return (
    <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
      <path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-4 4"/>
    </svg>
  );
}

function IconMoon() {
  return (
    <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  );
}

function IconSun() {
  return (
    <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="5"/>
      <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
    </svg>
  );
}

function IconChevron() {
  return (
    <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
      <path d="m15 18-6-6 6-6"/>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Health status dot
// ---------------------------------------------------------------------------

type HealthStatus = 'loading' | 'ok' | 'degraded';

function StatusDot({ status }: { status: HealthStatus }) {
  const colors: Record<HealthStatus, string> = {
    loading:  'bg-gray-400',
    ok:       'bg-emerald-400',
    degraded: 'bg-amber-400',
  };
  const labels: Record<HealthStatus, string> = {
    loading:  'Checking…',
    ok:       'All systems ok',
    degraded: 'Degraded',
  };
  return (
    <div className="flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
      <span
        className={`h-2 w-2 rounded-full ${colors[status]} ${status === 'loading' ? 'animate-pulse' : ''}`}
      />
      <span className="hidden lg:block">{labels[status]}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Nav item
// ---------------------------------------------------------------------------

const NAV = [
  { to: '/',         label: 'RAG Chat',    Icon: IconSearch },
  { to: '/agents',   label: 'Agent Trace', Icon: IconBot },
  { to: '/pipeline', label: 'Pipeline',    Icon: IconChart },
];

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const [dark, setDark] = useState<boolean>(() => localStorage.getItem('nexus-dark') === 'true');
  const [collapsed, setCollapsed] = useState<boolean>(false);
  const [health, setHealth] = useState<HealthStatus>('loading');
  const location = useLocation();

  // Apply/remove dark class on <html>
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('nexus-dark', String(dark));
  }, [dark]);

  // Collapse sidebar on small screens on route change
  useEffect(() => {
    if (window.innerWidth < 768) setCollapsed(true);
  }, [location.pathname]);

  // Health polling — every 60 seconds
  const checkHealth = useCallback(async () => {
    try {
      const res: HealthResponse = await nexusApi.getHealth();
      setHealth(res.status === 'ok' ? 'ok' : 'degraded');
    } catch {
      setHealth('degraded');
    }
  }, []);

  useEffect(() => {
    checkHealth();
    const id = setInterval(checkHealth, 60_000);
    return () => clearInterval(id);
  }, [checkHealth]);

  const sidebarW = collapsed ? 'w-16' : 'w-56';

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50 dark:bg-gray-950 font-sans">
      {/* ── Sidebar ─────────────────────────────────────── */}
      <aside
        className={`
          flex flex-col flex-shrink-0 transition-all duration-200
          ${sidebarW}
          bg-white border-r border-gray-200
          dark:bg-gray-900 dark:border-gray-800
        `}
      >
        {/* Logo + collapse toggle */}
        <div className="flex items-center justify-between px-4 py-5 border-b border-gray-100 dark:border-gray-800">
          {!collapsed && (
            <span className="font-bold text-gray-900 dark:text-white tracking-tight text-lg">
              Nexus<span className="text-brand-500">.</span>
            </span>
          )}
          <button
            onClick={() => setCollapsed(c => !c)}
            className={`
              p-1.5 rounded-lg text-gray-400 hover:text-gray-700
              dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800
              transition-colors ${collapsed ? 'mx-auto rotate-180' : ''}
            `}
            aria-label="Toggle sidebar"
          >
            <IconChevron />
          </button>
        </div>

        {/* Nav items */}
        <nav className="flex-1 px-2 py-4 space-y-1">
          {NAV.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors
                ${isActive
                  ? 'bg-brand-50 text-brand-700 dark:bg-brand-900 dark:text-white'
                  : 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200'
                }`
              }
            >
              <span className="flex-shrink-0"><Icon /></span>
              {!collapsed && <span className="truncate">{label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* Bottom: status + dark mode */}
        <div className="px-3 pb-5 space-y-3 border-t border-gray-100 dark:border-gray-800 pt-3">
          {!collapsed && <StatusDot status={health} />}
          {collapsed && (
            <div className="flex justify-center">
              <StatusDot status={health} />
            </div>
          )}
          <button
            onClick={() => setDark(d => !d)}
            className={`
              flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm
              text-gray-500 hover:bg-gray-100 dark:text-gray-400
              dark:hover:bg-gray-800 transition-colors
            `}
            aria-label="Toggle dark mode"
          >
            <span className="flex-shrink-0">{dark ? <IconSun /> : <IconMoon />}</span>
            {!collapsed && <span>{dark ? 'Light mode' : 'Dark mode'}</span>}
          </button>
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto">
        <Routes>
          <Route path="/"         element={<RagChat />} />
          <Route path="/agents"   element={<AgentTracer />} />
          <Route path="/pipeline" element={<Pipeline />} />
        </Routes>
      </main>
    </div>
  );
}