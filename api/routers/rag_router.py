"""
api/routers/rag_router.py
=========================
RAG router for Nexus-AI.

Phase 1 Day 4: /ingest endpoint implemented.
Phase 1 Day 5: /query endpoint implemented (retriever).

Endpoints:
  POST /api/rag/ingest  → ingest document into ChromaDB
  POST /api/rag/query   → hybrid search + rerank + LLM answer
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.rag.ingestor import ingest
from api.rag.retriever import QueryResult
from api.rag.retriever import query as rag_query

router = APIRouter(prefix="/api/rag", tags=["RAG"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    source: str          # file path, URL, or raw text
    doc_type: str | None = None
    metadata: dict       = {}


class IngestResponse(BaseModel):
    source:      str
    doc_type:    str
    chunk_count: int
    duration_ms: int


class QueryRequest(BaseModel):
    query:  str
    top_k:  int  = 3
    stream: bool = False   # kept for future streaming support


class MessageResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# POST /api/rag/ingest
# ---------------------------------------------------------------------------

@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=200,
    summary="Ingest a document into ChromaDB",
    description="Loads, chunks, embeds, and upserts a document. Supports PDF, DOCX, MD, TXT, URL.",
)
async def ingest_document(body: IngestRequest) -> IngestResponse:
    """
    Ingest a document into the nexus_knowledge ChromaDB collection.

    - source: file path, https:// URL, or raw text string
    - doc_type: optional override; auto-detected from source if omitted
    - metadata: extra key-value pairs stored alongside every chunk
    """
    try:
        result = await ingest(
            source=body.source,
            doc_type=body.doc_type or None,
            metadata=body.metadata or {},
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"File not found: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingest failed: {exc}")

    if result.errors:
        raise HTTPException(status_code=422, detail=result.errors[0])

    return IngestResponse(
        source=result.source,
        doc_type=result.doc_type,
        chunk_count=result.chunk_count,
        duration_ms=result.duration_ms,
    )


# ---------------------------------------------------------------------------
# POST /api/rag/query
# ---------------------------------------------------------------------------

@router.post(
    "/query",
    response_model=QueryResult,
    status_code=200,
    summary="Query the RAG knowledge base",
    description="Hybrid semantic + BM25 retrieval, cross-encoder reranking, LLM answer with citations.",
)
async def query_knowledge_base(body: QueryRequest) -> QueryResult:
    """
    Full RAG pipeline:
      1. Embed query → semantic search (ChromaDB)
      2. BM25 keyword search over corpus
      3. Hybrid merge + cross-encoder rerank
      4. Build context → LLM answer (via llm_router — respects PRIVACY_MODE)
      5. Log to rag_queries table
      6. Return answer + sources + latency_ms
    """
    try:
        result = await rag_query(
            q=body.query,
            top_k=body.top_k,
            stream=body.stream,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Query failed: {exc}")

    return result