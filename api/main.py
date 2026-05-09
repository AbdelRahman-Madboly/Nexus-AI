"""
api/main.py
===========
FastAPI application entry point for Nexus-AI.

Responsibilities:
  - Create the FastAPI app with lifespan (startup/shutdown)
  - Call init_db() exactly once at startup
  - Register CORS middleware (dev mode — all origins)
  - Mount all 3 routers (rag, agents, mcp)
  - Mount FastMCP SSE transport at /mcp for Claude Desktop
  - Expose GET /api/health with real component status checks

Phase history:
  v0.1.0 — Phase 0: foundation, LLM router, health endpoint
  v0.2.0 — Phase 1: RAG engine wired (rag_router live)
  v0.3.0 — Phase 2: LangGraph agents wired (agent_router live)
  v0.3.0 — Phase 3: MCP server mounted (mcp_router live + /mcp SSE)

Rules enforced:
  - All settings from api/config.py — zero hardcoded values
  - All LLM calls go through api/llm/llm_router.py
  - Every endpoint has typed Pydantic response models — no dict/Any
  - async/await throughout
"""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.database import init_db
from api.models.crm_models import HealthComponent, HealthResponse
from api.routers import agent_router, mcp_router, rag_router
from api.mcp.server import mcp   # FastMCP singleton — tools registered at import time

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — startup + shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once at startup (before first request) and once at shutdown.
    init_db() is called here — exactly one time per process.
    """
    logger.info("Nexus-AI starting up...")
    await init_db()
    logger.info("Startup complete — all systems ready.")
    yield
    logger.info("Nexus-AI shutting down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

settings = get_settings()

app = FastAPI(
    title="Nexus-AI",
    version="0.3.0",
    description=(
        "AI-augmented business operations platform. "
        "RAG · LangGraph Agents · MCP · OpenClaw · n8n · React Dashboard."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# CORS Middleware — dev mode (all origins)
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # tighten to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routers — must be included BEFORE the /mcp SSE mount.
# FastAPI processes include_router() registrations in order; the SSE mount
# is a Starlette sub-application that catches all paths under /mcp, so
# routers must be wired first to avoid shadowing /api/mcp/tools.
# ---------------------------------------------------------------------------

app.include_router(rag_router.router)
app.include_router(agent_router.router)
app.include_router(mcp_router.router)     # registers GET /api/mcp/tools

# Mount MCP SSE transport — Claude Desktop connects to http://localhost:8000/mcp/sse
# This MUST come after include_router(mcp_router.router) — see note above.
app.mount("/mcp", mcp.http_app(path="/sse", transport="sse"))


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

async def _check_ollama() -> HealthComponent:
    """Ping Ollama and return its health status."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(settings.ollama_base_url)
        if response.status_code == 200:
            return HealthComponent(status="ok")
        return HealthComponent(status="down", detail=f"HTTP {response.status_code}")
    except Exception as exc:
        return HealthComponent(status="down", detail=str(exc))


async def _check_database() -> HealthComponent:
    """Verify the SQLite database is reachable."""
    try:
        import aiosqlite
        async with aiosqlite.connect(settings.sqlite_db_path) as conn:
            await conn.execute("SELECT 1")
        return HealthComponent(status="ok")
    except Exception as exc:
        return HealthComponent(status="down", detail=str(exc))


@app.get(
    "/api/health",
    response_model=HealthResponse,
    summary="System health check",
    tags=["Health"],
)
async def health_check() -> HealthResponse:
    """
    Returns real-time status of all critical components:
      - database    : SQLite connectivity check
      - ollama      : HTTP ping to Ollama server
      - llm_backend : which backend is active (respects PRIVACY_MODE)
    """
    db_status     = await _check_database()
    ollama_status = await _check_ollama()
    llm_status    = HealthComponent(
        status="ok",
        detail=settings.effective_llm_backend,
    )

    overall = (
        "ok"
        if db_status.status == "ok" and ollama_status.status == "ok"
        else "degraded"
    )

    return HealthResponse(
        status=overall,
        components={
            "database":    db_status,
            "ollama":      ollama_status,
            "llm_backend": llm_status,
        },
    )