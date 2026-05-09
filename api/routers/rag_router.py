"""
api/routers/rag_router.py
=========================
RAG (Retrieval-Augmented Generation) router for Nexus-AI.

Phase 0 — placeholder endpoints.
Real implementation (ingestor + retriever) is built in Phase 1, Days 4–5.

Endpoints:
  POST /api/rag/ingest  → 501 until Phase 1
  POST /api/rag/query   → 501 until Phase 1
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/rag", tags=["RAG"])


# ---------------------------------------------------------------------------
# Shared response model — used by both placeholder endpoints
# ---------------------------------------------------------------------------

class MessageResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# Request models (typed, even for placeholders)
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    source: str  # file path, URL, or raw text
    metadata: dict = {}


class QueryRequest(BaseModel):
    query: str
    top_k: int = 3
    stream: bool = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/ingest",
    response_model=MessageResponse,
    status_code=501,
    summary="Ingest a document into ChromaDB",
    description="Phase 1 — not yet implemented.",
)
async def ingest_document(body: IngestRequest) -> JSONResponse:
    """
    Accepts a document source (file path, URL, or text) and ingests it
    into ChromaDB with embeddings.  Built in Phase 1, Day 4.
    """
    return JSONResponse(
        status_code=501,
        content={"detail": "RAG ingestor not yet implemented"},
    )


@router.post(
    "/query",
    response_model=MessageResponse,
    status_code=501,
    summary="Query the RAG knowledge base",
    description="Phase 1 — not yet implemented.",
)
async def query_knowledge_base(body: QueryRequest) -> JSONResponse:
    """
    Embeds the query, retrieves relevant chunks via hybrid search,
    reranks, and streams an LLM answer with citations.  Built in Phase 1, Day 5.
    """
    return JSONResponse(
        status_code=501,
        content={"detail": "RAG retriever not yet implemented"},
    )