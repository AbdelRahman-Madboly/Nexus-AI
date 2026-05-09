"""
api/rag/ingestor.py
===================
Document ingestor for Nexus-AI RAG engine.

Supports: PDF · Markdown · DOCX · plain text · URLs
Pipeline:  load → clean → chunk → embed (Ollama) → upsert (ChromaDB)

Loaders:
  - PDF      → pypdf PdfReader
  - DOCX     → python-docx Document
  - MD / TXT → plain UTF-8 read
  - URL      → httpx GET + BeautifulSoup text extraction
  - Raw text → passed directly (doc_type="text")

Chunking:
  - RecursiveCharacterTextSplitter: 512 chars, 64 overlap
  - Separators: paragraph → sentence → word

Embedding:
  - llm_router.embed() → Ollama nomic-embed-text (768-dim, always local)

ChromaDB:
  - Collection : "nexus_knowledge"
  - Client     : chromadb.HttpClient (sync) — run in executor to avoid blocking
  - IDs        : sha256(source + ":" + str(chunk_index))[:16]
  - Metadata   : source, doc_type, chunk_index, total_chunks, ingested_at

Public API:
  ingest(source, doc_type=None, metadata=None) -> IngestResult
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import chromadb
import httpx
from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter

from api.config import get_settings
from api.llm import llm_router

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLLECTION_NAME = "nexus_knowledge"
CHUNK_SIZE      = 512
CHUNK_OVERLAP   = 64

_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
    length_function=len,
)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class IngestResult:
    source:      str
    doc_type:    str
    chunk_count: int
    duration_ms: int
    errors:      list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ChromaDB client — lazy singleton (sync HttpClient, used via run_in_executor)
# ---------------------------------------------------------------------------

_chroma_client: Optional[chromadb.HttpClient] = None


def _get_chroma_sync() -> chromadb.HttpClient:
    """Return (or create) the shared sync ChromaDB HttpClient."""
    global _chroma_client
    if _chroma_client is None:
        settings = get_settings()
        _chroma_client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )
        logger.info(
            "ChromaDB client connected → %s:%s",
            settings.chroma_host,
            settings.chroma_port,
        )
    return _chroma_client


async def _get_chroma() -> chromadb.HttpClient:
    """Async wrapper — runs sync client init in executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_chroma_sync)


# ---------------------------------------------------------------------------
# Document loaders
# ---------------------------------------------------------------------------

def _detect_doc_type(source: str) -> str:
    s = source.strip().lower()
    if s.startswith("http://") or s.startswith("https://"):
        return "url"
    suffix = Path(s).suffix.lstrip(".")
    if suffix in {"pdf", "docx", "md", "txt"}:
        return suffix
    return "text"


def _load_pdf(path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text.strip())
    return "\n\n".join(pages)


def _load_docx(path: str) -> str:
    from docx import Document
    doc = Document(path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _load_md_or_txt(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


async def _load_url(url: str) -> str:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(
            url, headers={"User-Agent": "NexusAI-Ingestor/1.0"}
        )
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    lines = [
        line.strip()
        for line in soup.get_text(separator="\n").splitlines()
        if line.strip()
    ]
    return "\n\n".join(lines)


async def _load_source(source: str, doc_type: str) -> str:
    if doc_type == "url":
        return await _load_url(source)
    if doc_type == "pdf":
        return _load_pdf(source)
    if doc_type == "docx":
        return _load_docx(source)
    if doc_type in {"md", "txt", "markdown"}:
        p = Path(source)
        if p.exists():
            return _load_md_or_txt(source)
        return source
    p = Path(source)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return source


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk(text: str) -> list[str]:
    return _SPLITTER.split_text(text)


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

async def _embed_batch(chunks: list[str]) -> list[list[float]]:
    vectors = []
    for chunk in chunks:
        vec = await llm_router.embed(chunk)
        vectors.append(vec)
    return vectors


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def _chunk_id(source: str, chunk_index: int) -> str:
    raw = f"{source}:{chunk_index}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


# ---------------------------------------------------------------------------
# ChromaDB operations — sync functions run via executor
# ---------------------------------------------------------------------------

def _chroma_get_or_create_collection(client: chromadb.HttpClient) -> chromadb.Collection:
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
    )

def _chroma_upsert(
    collection: chromadb.Collection,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict],
    embeddings: list[list[float]],
) -> None:
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def ingest(
    source: str,
    doc_type: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> IngestResult:
    """
    Ingest a document into ChromaDB.

    Args:
        source:   File path, URL, or raw text string.
        doc_type: "pdf" | "docx" | "md" | "txt" | "url" | "text".
                  Auto-detected from source if not provided.
        metadata: Extra key-value pairs merged into every chunk's ChromaDB metadata.

    Returns:
        IngestResult(source, doc_type, chunk_count, duration_ms, errors)
    """
    start  = time.monotonic()
    errors: list[str] = []
    loop   = asyncio.get_event_loop()

    # 1. Detect doc type
    resolved_type = doc_type or _detect_doc_type(source)
    logger.info("Ingestor | source=%s | doc_type=%s", source[:80], resolved_type)

    # 2. Load raw text
    raw_text = await _load_source(source, resolved_type)
    if not raw_text.strip():
        logger.warning("Ingestor | empty document — nothing to ingest.")
        return IngestResult(
            source=source,
            doc_type=resolved_type,
            chunk_count=0,
            duration_ms=0,
            errors=["Document is empty after loading."],
        )

    # 3. Chunk
    chunks = _chunk(raw_text)
    total  = len(chunks)
    logger.info("Ingestor | chunks=%d", total)

    # 4. Embed
    embeddings = await _embed_batch(chunks)

    # 5. Build upsert payload
    ingested_at = datetime.now(timezone.utc).isoformat()
    base_meta   = {
        "source":       source,
        "doc_type":     resolved_type,
        "total_chunks": total,
        "ingested_at":  ingested_at,
        **(metadata or {}),
    }
    ids   = [_chunk_id(source, i) for i in range(total)]
    metas = [{**base_meta, "chunk_index": i} for i in range(total)]

    # 6. Upsert into ChromaDB (sync client → run in executor)
    client     = await _get_chroma()
    collection = await loop.run_in_executor(
        None, _chroma_get_or_create_collection, client
    )
    await loop.run_in_executor(
        None, _chroma_upsert, collection, ids, chunks, metas, embeddings
    )

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info("Ingestor | done | chunks=%d | duration_ms=%d", total, duration_ms)

    return IngestResult(
        source=source,
        doc_type=resolved_type,
        chunk_count=total,
        duration_ms=duration_ms,
        errors=errors,
    )