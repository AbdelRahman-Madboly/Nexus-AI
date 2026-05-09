"""
api/llm/openai_client.py
========================
Async OpenAI client for Nexus-AI.

Uses the official `openai` SDK (AsyncOpenAI).
This file is ONLY imported by llm_router.py — never by feature code directly.

Functions:
  complete(prompt, system, model) → str
"""

import logging

from openai import AsyncOpenAI

from api.config import get_settings

logger = logging.getLogger(__name__)


async def complete(
    prompt: str,
    system: str = "",
    model: str | None = None,
) -> str:
    """
    Send a chat completion request to OpenAI.
    Returns the assistant's reply as a plain string.

    Args:
        prompt: The user message.
        system: Optional system prompt.
        model:  OpenAI model name. Defaults to settings.openai_model.
    """
    settings = get_settings()
    model = model or settings.openai_model

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    logger.debug("OpenAI complete | model=%s | prompt_len=%d", model, len(prompt))

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
    )

    text = response.choices[0].message.content or ""
    logger.debug("OpenAI complete | response_len=%d", len(text))
    return text