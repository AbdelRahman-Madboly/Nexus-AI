"""
api/llm/llm_router.py
=====================
Central LLM router for Nexus-AI.

This is the ONLY file that feature code (agents, RAG, routers) imports for LLM calls.
It reads effective_llm_backend from config — which already enforces PRIVACY_MODE —
and delegates to the correct client.

Rule: PRIVACY_MODE=true → effective_llm_backend returns 'ollama' → always Ollama.
      No other file in the project imports openai/anthropic/google directly.

Public API:
  complete(prompt, system, model) → str
  embed(text, model)              → list[float]   (always Ollama — embeddings are local)
"""

import logging
from typing import Literal

from api.config import get_settings

logger = logging.getLogger(__name__)

# Valid backend literals — matches Settings.llm_backend type
Backend = Literal["openai", "claude", "gemini", "ollama"]


async def complete(
    prompt: str,
    system: str = "",
    model: str | None = None,
) -> str:
    """
    Route a completion request to the correct LLM backend.

    Backend selection order:
      1. If PRIVACY_MODE=true  → always Ollama (enforced by effective_llm_backend)
      2. Else use LLM_BACKEND from .env: openai | claude | gemini | ollama

    Args:
        prompt: The user message.
        system: Optional system prompt. Pass "" to omit.
        model:  Override the default model for the chosen backend.
                If None, each client uses its own settings default.

    Returns:
        The assistant's reply as a plain string.

    Raises:
        ValueError: If LLM_BACKEND is set to an unrecognised value.
        Any SDK/HTTP exception from the underlying client.
    """
    backend: Backend = get_settings().effective_llm_backend
    logger.info("LLM router | backend=%s | privacy_mode=%s", backend, get_settings().privacy_mode)

    if backend == "ollama":
        from api.llm.ollama_client import complete as _complete
        return await _complete(prompt, system=system, model=model)

    elif backend == "openai":
        from api.llm.openai_client import complete as _complete
        return await _complete(prompt, system=system, model=model)

    elif backend == "claude":
        from api.llm.claude_client import complete as _complete
        return await _complete(prompt, system=system, model=model)

    elif backend == "gemini":
        from api.llm.gemini_client import complete as _complete
        return await _complete(prompt, system=system, model=model)

    else:
        raise ValueError(
            f"Unknown LLM_BACKEND '{backend}'. "
            "Valid values: openai | claude | gemini | ollama"
        )


async def embed(
    text: str,
    model: str | None = None,
) -> list[float]:
    """
    Generate an embedding vector.

    Embeddings are ALWAYS routed to Ollama regardless of LLM_BACKEND or PRIVACY_MODE.
    Reason: embeddings must be consistent across ingest and query — mixing providers
    would produce incompatible vectors in ChromaDB. Ollama + nomic-embed-text is the
    single embedding source for the entire project.

    Args:
        text:  Text to embed.
        model: Override the default embed model (settings.ollama_embed_model).

    Returns:
        A list of floats — the embedding vector.
    """
    from api.llm.ollama_client import embed as _embed
    logger.debug("LLM router | embed | always=ollama | text_len=%d", len(text))
    return await _embed(text, model=model)