"""
api/llm/ollama_client.py
========================
Async Ollama client for Nexus-AI.

Uses httpx.AsyncClient to call the Ollama REST API directly — no SDK needed.
This is the ONLY file that talks to Ollama. All other code goes through llm_router.py.

Functions:
  complete(prompt, system, model) → str
  embed(text, model)              → list[float]
"""

import logging

import httpx

from api.config import get_settings

logger = logging.getLogger(__name__)


async def complete(
    prompt: str,
    system: str = "",
    model: str | None = None,
) -> str:
    """
    Send a chat completion request to Ollama.
    Returns the assistant's reply as a plain string.

    Args:
        prompt: The user message.
        system: Optional system prompt. Empty string = no system message.
        model:  Ollama model name. Defaults to settings.ollama_model.
    """
    settings = get_settings()
    model = model or settings.ollama_model
    base_url = settings.ollama_base_url

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,   # plain JSON response — streaming added in Phase 1
    }

    logger.debug("Ollama complete | model=%s | prompt_len=%d", model, len(prompt))

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base_url}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    text = data["message"]["content"]
    logger.debug("Ollama complete | response_len=%d", len(text))
    return text


async def embed(
    text: str,
    model: str | None = None,
) -> list[float]:
    """
    Generate an embedding vector for the given text using Ollama.

    Embeddings are ALWAYS local (Ollama) regardless of LLM_BACKEND or PRIVACY_MODE.
    This function is called directly by the RAG retriever — never via the LLM router
    for backend selection, but llm_router.embed() delegates here.

    Args:
        text:  The text to embed.
        model: Embedding model name. Defaults to settings.ollama_embed_model.

    Returns:
        A list of floats representing the embedding vector.
    """
    settings = get_settings()
    model = model or settings.ollama_embed_model
    base_url = settings.ollama_base_url

    payload = {"model": model, "input": text}

    logger.debug("Ollama embed | model=%s | text_len=%d", model, len(text))

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{base_url}/api/embed",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    # Ollama /api/embed returns {"embeddings": [[...floats...]]}
    vector = data["embeddings"][0]
    logger.debug("Ollama embed | vector_dim=%d", len(vector))
    return vector