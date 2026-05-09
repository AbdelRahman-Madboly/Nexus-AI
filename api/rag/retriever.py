from typing import Optional
"""
api/rag/retriever.py
====================
Hybrid RAG retriever for Nexus-AI.

Pipeline:
  query → embed → semantic_search (ChromaDB)
                + bm25_search     (in-memory BM25 over ChromaDB corpus)
         → hybrid_merge (deduplicate, keep best score)
         → rerank       (CrossEncoder ms-marco-MiniLM-L-6-v2)
         → build context string
         → complete()   (LLM answer via llm_router — respects LLM_BACKEND + PRIVACY_MODE)
         → log to rag_queries table
         → return QueryResult

Public API:
  query(q, top_k=3, stream=False) -> QueryResult

Why hybrid?
  Semantic search finds conceptually similar chunks even if exact words differ.
  BM25 finds chunks that share exact keywords with the query.
  Together they catch what either alone would miss — especially for named entities,
  product names, and numbers (e.g. "70%", "Revenyu") where keyword match matters.

Why cross-encoder reranking?
  ChromaDB distances and BM25 scores are not comparable — they measure different
  things. A cross-encoder reads the query AND each candidate together, giving a
  single calibrated relevance score. The top_k after reranking are the genuinely
  most relevant chunks, not the most similar vectors.
"""

import asyncio
import json
import logging
import time
from uuid import uuid4

import chromadb
from pydantic import BaseModel
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from api.config import get_settings
from api.database import get_db
from api.llm.llm_router import complete, embed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — must match ingestor.py exactly
# ---------------------------------------------------------------------------

COLLECTION_NAME = "nexus_knowledge"

# ---------------------------------------------------------------------------
# Cross-encoder reranker — loaded once at module import time.
# First import triggers a ~90MB model download (cached after that).
# ms-marco-MiniLM-L-6-v2 is the standard lightweight reranker for RAG pipelines.
# ---------------------------------------------------------------------------

_reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
logger.info("CrossEncoder loaded: cross-encoder/ms-marco-MiniLM-L-6-v2")

# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class QueryResult(BaseModel):
    answer: str
    sources: list[dict]   # each: {id, text, metadata, score}
    latency_ms: int


# ---------------------------------------------------------------------------
# ChromaDB client — same lazy singleton pattern as ingestor.py.
# Sync HttpClient wrapped in run_in_executor wherever called from async context.
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
    """Async wrapper — runs sync client init in executor to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_chroma_sync)


# ---------------------------------------------------------------------------
# Sync ChromaDB helpers — named functions (not lambdas) for executor safety
# ---------------------------------------------------------------------------


def _chroma_get_collection(client: chromadb.HttpClient) -> chromadb.Collection:
    """Get the nexus_knowledge collection. Creates it if it doesn't exist yet."""
    return client.get_or_create_collection(name=COLLECTION_NAME)


def _chroma_query(
    collection: chromadb.Collection,
    vector: list[float],
    n_results: int,
) -> dict:
    """
    Run a vector similarity query against ChromaDB.
    Returns the raw ChromaDB result dict with ids, documents, metadatas, distances.
    """
    return collection.query(
        query_embeddings=[vector],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )


def _chroma_get_all(collection: chromadb.Collection) -> dict:
    """
    Fetch the full corpus from ChromaDB (ids + documents + metadatas).
    Used by BM25 — BM25 needs ALL documents to build its index.
    """
    return collection.get(include=["documents", "metadatas"])


# ---------------------------------------------------------------------------
# Semantic search — vector similarity via ChromaDB
# ---------------------------------------------------------------------------


async def semantic_search(query: str, top_k: int = 10) -> list[dict]:
    """
    Embed the query and find the top_k most similar chunks in ChromaDB.

    Returns list of dicts: {id, text, metadata, score}
    Score = ChromaDB distance (lower is more similar — cosine by default).

    Returns [] if the collection is empty (e.g. nothing ingested yet).
    """
    # 1. Embed the query — always Ollama nomic-embed-text via llm_router
    vector = await embed(query)

    # 2. Run ChromaDB query in executor (sync client)
    loop = asyncio.get_event_loop()
    client = await _get_chroma()
    collection = await loop.run_in_executor(None, _chroma_get_collection, client)

    try:
        raw = await loop.run_in_executor(
            None, _chroma_query, collection, vector, top_k
        )
    except Exception as exc:
        # ChromaDB raises if collection is empty or n_results > corpus size
        logger.warning("semantic_search: ChromaDB query failed — %s", exc)
        return []

    # 3. Unpack ChromaDB result arrays (each is a list-of-lists because we sent 1 query)
    ids        = raw.get("ids",        [[]])[0]
    documents  = raw.get("documents",  [[]])[0]
    metadatas  = raw.get("metadatas",  [[]])[0]
    distances  = raw.get("distances",  [[]])[0]

    if not ids:
        return []

    results = []
    for chunk_id, text, meta, dist in zip(ids, documents, metadatas, distances):
        results.append({
            "id":       chunk_id,
            "text":     text,
            "metadata": meta or {},
            "score":    float(dist),   # lower = more similar
        })

    logger.debug("semantic_search | query=%s | hits=%d", query[:60], len(results))
    return results


# ---------------------------------------------------------------------------
# BM25 search — keyword-based retrieval over the full ChromaDB corpus
# ---------------------------------------------------------------------------


def bm25_search(query: str, corpus_ids: list[str], corpus_docs: list[str],
                corpus_metas: list[dict], top_k: int = 10) -> list[dict]:
    """
    Build a BM25 index over the provided corpus and score the query against it.

    Why pass corpus as arguments rather than re-fetching from ChromaDB?
    The caller (query()) already fetched the full corpus once; we reuse it
    to avoid a second ChromaDB round-trip.

    Tokenization: lowercase whitespace split — simple but effective for BM25.
    BM25 works on term frequency, so exact keyword matches score highly.

    Returns [] if corpus is empty.
    """
    if not corpus_docs:
        return []

    # Tokenize corpus — BM25Okapi expects list[list[str]]
    tokenized_corpus = [doc.lower().split() for doc in corpus_docs]
    bm25 = BM25Okapi(tokenized_corpus)

    # Score the query tokens against every document
    query_tokens = query.lower().split()
    scores = bm25.get_scores(query_tokens)   # returns ndarray, one score per doc

    # Pair with ids and sort descending by score
    scored = sorted(
        zip(scores, corpus_ids, corpus_docs, corpus_metas),
        key=lambda x: x[0],
        reverse=True,
    )

    results = []
    for score, chunk_id, text, meta in scored[:top_k]:
        if float(score) == 0.0:
            # BM25 score of 0 means no term overlap at all — not useful
            break
        results.append({
            "id":       chunk_id,
            "text":     text,
            "metadata": meta or {},
            "score":    float(score),   # higher = more relevant (opposite of semantic)
        })

    logger.debug("bm25_search | query=%s | hits=%d", query[:60], len(results))
    return results


# ---------------------------------------------------------------------------
# Hybrid merge — combine semantic + BM25 results, deduplicate
# ---------------------------------------------------------------------------


def hybrid_merge(
    semantic: list[dict],
    bm25: list[dict],
) -> list[dict]:
    """
    Combine semantic and BM25 results into a single deduplicated candidate list.

    Deduplication rule: if a chunk appears in both lists, keep the semantic result
    (lower distance score = objectively more similar in vector space).
    BM25 scores and semantic distances are on different scales, so we do NOT
    combine them numerically — the cross-encoder reranker handles final ordering.

    Result is unsorted; the caller passes it to rerank().
    """
    seen:    dict[str, dict] = {}   # chunk_id → best result dict

    # Add semantic results first — these take priority on duplicates
    for item in semantic:
        seen[item["id"]] = item

    # Add BM25 results only for ids not already captured by semantic
    for item in bm25:
        if item["id"] not in seen:
            seen[item["id"]] = item

    merged = list(seen.values())
    logger.debug("hybrid_merge | semantic=%d bm25=%d merged=%d",
                 len(semantic), len(bm25), len(merged))
    return merged


# ---------------------------------------------------------------------------
# Cross-encoder reranker
# ---------------------------------------------------------------------------


def rerank(query: str, candidates: list[dict], top_k: int = 3) -> list[dict]:
    """
    Re-score each candidate by passing (query, chunk_text) through a cross-encoder.

    Why cross-encoder rather than just sorting by vector distance?
    Vector embeddings encode the MEANING of text independently — the model never
    sees query and chunk together. A cross-encoder reads both simultaneously,
    giving a much more accurate relevance score for the specific query.

    The ms-marco model was trained on 500k+ passage ranking pairs — it understands
    what makes a passage a good answer to a question.

    Returns the top_k most relevant candidates, sorted by score descending.
    """
    if not candidates:
        return []

    pairs  = [(query, c["text"]) for c in candidates]
    scores = _reranker.predict(pairs)   # returns ndarray, one score per pair

    # Attach reranker scores and sort
    ranked = sorted(
        zip(scores, candidates),
        key=lambda x: x[0],
        reverse=True,
    )

    top = []
    for score, candidate in ranked[:top_k]:
        # Overwrite "score" with the reranker's score for clarity
        top.append({**candidate, "score": float(score)})

    logger.debug("rerank | candidates=%d → top_k=%d", len(candidates), len(top))
    return top


# ---------------------------------------------------------------------------
# Public query function
# ---------------------------------------------------------------------------


async def query(q: str, top_k: int = 3, stream: bool = False) -> QueryResult:
    """
    Full RAG query pipeline:
      1. Fetch full corpus from ChromaDB (needed for BM25)
      2. Run semantic_search and bm25_search concurrently
      3. Hybrid merge + cross-encoder rerank
      4. Build context string from top_k chunks
      5. Call LLM with grounded system prompt → answer
      6. Log query + answer to rag_queries table
      7. Return QueryResult

    stream=True is accepted for API compatibility but currently ignored —
    streaming support will be added in the dashboard phase.
    """
    start = time.monotonic()
    loop  = asyncio.get_event_loop()

    logger.info("RAG query | q=%s | top_k=%d", q[:80], top_k)

    # ------------------------------------------------------------------
    # 1. Fetch full corpus once — reused by BM25 to avoid a 2nd round-trip
    # ------------------------------------------------------------------
    client     = await _get_chroma()
    collection = await loop.run_in_executor(None, _chroma_get_collection, client)

    try:
        corpus_raw = await loop.run_in_executor(None, _chroma_get_all, collection)
    except Exception as exc:
        logger.warning("query: failed to fetch corpus — %s", exc)
        corpus_raw = {"ids": [], "documents": [], "metadatas": []}

    corpus_ids   = corpus_raw.get("ids",       [])
    corpus_docs  = corpus_raw.get("documents", [])
    corpus_metas = corpus_raw.get("metadatas", [])

    if not corpus_docs:
        logger.warning("query: ChromaDB collection is empty — returning no-context answer")
        return QueryResult(
            answer="I don't have any documents in the knowledge base yet. "
                   "Please ingest some documents first using POST /api/rag/ingest.",
            sources=[],
            latency_ms=0,
        )

    # ------------------------------------------------------------------
    # 2. Semantic search and BM25 run concurrently.
    # BM25 is sync (CPU-only) — run it in executor to avoid blocking the loop.
    # ------------------------------------------------------------------
    semantic_task = semantic_search(q, top_k=10)
    bm25_task     = loop.run_in_executor(
        None, bm25_search, q, corpus_ids, corpus_docs, corpus_metas, 10
    )

    semantic_results, bm25_results = await asyncio.gather(semantic_task, bm25_task)

    # ------------------------------------------------------------------
    # 3. Merge and rerank
    # Reranking is CPU-bound (CrossEncoder inference) — run in executor.
    # ------------------------------------------------------------------
    merged = hybrid_merge(semantic_results, bm25_results)

    top_chunks = await loop.run_in_executor(None, rerank, q, merged, top_k)

    if not top_chunks:
        logger.warning("query: reranker returned no chunks")
        return QueryResult(
            answer="I don't have enough information in the knowledge base to answer that question.",
            sources=[],
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    # ------------------------------------------------------------------
    # 4. Build context string — numbered so the LLM can cite [1], [2], etc.
    # ------------------------------------------------------------------
    context = "\n\n".join(
        [f"[{i + 1}] {c['text']}" for i, c in enumerate(top_chunks)]
    )

    system_prompt = (
        "You are Nexus, a business AI assistant. Answer the user's question using ONLY "
        "the context below. If the answer is not in the context, say \"I don't have that "
        "information in the knowledge base.\" Always cite the source number [1], [2], [3] "
        "when you use information from a chunk.\n\n"
        f"Context:\n{context}"
    )

    # ------------------------------------------------------------------
    # 5. Generate answer via LLM router (respects LLM_BACKEND + PRIVACY_MODE)
    # ------------------------------------------------------------------
    answer = await complete(q, system=system_prompt)

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info("RAG query | done | latency_ms=%d | answer_len=%d", latency_ms, len(answer))

    # ------------------------------------------------------------------
    # 6. Log to rag_queries table
    # source_ids logged as JSON array of chunk IDs for traceability
    # ------------------------------------------------------------------
    source_ids = [c["id"] for c in top_chunks]
    model_used = get_settings().effective_llm_backend

    try:
        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO rag_queries
                    (id, query_text, response_text, sources_json, latency_ms, model_used)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    q,
                    answer,
                    json.dumps(source_ids),
                    latency_ms,
                    model_used,
                ),
            )
            await db.commit()
    except Exception as exc:
        # Logging failure must never break the query response
        logger.error("query: failed to log to rag_queries — %s", exc)

    # ------------------------------------------------------------------
    # 7. Return result
    # ------------------------------------------------------------------
    return QueryResult(
        answer=answer,
        sources=top_chunks,
        latency_ms=latency_ms,
    )