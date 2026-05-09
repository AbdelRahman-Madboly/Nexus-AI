"""
api/routers/rag_router.py
=========================
RAG router for Nexus-AI.

Phase 1 Day 4: /ingest endpoint implemented.
Phase 1 Day 5: /query endpoint implemented (retriever).

Endpoints:
  POST /api/rag/ingest  → ingest document into ChromaDB
  POST /api/rag/query   → 501 until Day 5
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.database import get_db
from api.models.crm_models import RagQueryCreate
from api.rag.ingestor import ingest

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
    stream: bool = False


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
# POST /api/rag/query  — 501 until Day 5
# ---------------------------------------------------------------------------

@router.post(
    "/query",
    response_model=MessageResponse,
    status_code=501,
    summary="Query the RAG knowledge base",
    description="Phase 1 Day 5 — not yet implemented.",
)
async def query_knowledge_base(body: QueryRequest) -> JSONResponse:
    """
    Hybrid semantic + BM25 retrieval with reranking and LLM answer generation.
    Built in Phase 1, Day 5.
    """
    return JSONResponse(
        status_code=501,
        content={"detail": "RAG retriever not yet implemented — coming Day 5"},
    )