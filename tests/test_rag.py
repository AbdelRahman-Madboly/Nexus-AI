"""
tests/test_rag.py
=================
Phase 1 RAG test suite — 10 business queries against ingested Projecx content.

Prerequisites (run these before pytest):
  1. docker-compose down && docker-compose up -d   (ChromaDB must be up)
  2. Wait ~20 seconds for services to start
  3. Ingest Projecx content:
       curl -X POST http://localhost:8000/api/rag/ingest \
         -H "Content-Type: application/json" \
         -d '{"source": "https://projecx.io"}'

Then run:
  python -m pytest tests/test_rag.py -v

Gate: 10/10 passing. Each test asserts answer is non-empty AND sources is non-empty.
"""

import pytest
import pytest_asyncio

from api.rag.retriever import query

# 10 business queries covering key Projecx facts
QUERIES = [
    "What is Revenyu?",
    "What is Bandora?",
    "What percentage of workflows is Projecx integrating AI into?",
    "What does Projecx do?",
    "Where is Projecx located?",
    "What AI models does Projecx use?",
    "What is the Human-AI model?",
    "What products does Projecx build?",
    "Who are Projecx's target customers?",
    "What is Projecx's AI strategy?",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("question", QUERIES)
async def test_rag_query_returns_answer(question: str) -> None:
    """
    Each query must return:
      - A non-empty answer string
      - At least one source chunk
      - A positive latency_ms
    """
    result = await query(question, top_k=3)

    assert isinstance(result.answer, str), \
        f"answer should be a string, got {type(result.answer)}"
    assert len(result.answer) > 0, \
        f"answer should not be empty for query: {question!r}"

    assert isinstance(result.sources, list), \
        f"sources should be a list, got {type(result.sources)}"
    assert len(result.sources) > 0, \
        f"sources should not be empty for query: {question!r}"

    assert result.latency_ms > 0, \
        f"latency_ms should be > 0, got {result.latency_ms}"

    # Print for visibility when running with -v
    print(f"\n[{question}]")
    print(f"  answer ({len(result.answer)} chars): {result.answer[:120]}...")
    print(f"  sources: {len(result.sources)} chunks")
    print(f"  latency_ms: {result.latency_ms}")