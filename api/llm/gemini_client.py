"""
api/llm/gemini_client.py
========================
Async Google Gemini client for Nexus-AI.

Uses the official `google-genai` SDK.
This file is ONLY imported by llm_router.py — never by feature code directly.

Functions:
  complete(prompt, system, model) → str
"""

import logging

from google import genai
from google.genai import types

from api.config import get_settings

logger = logging.getLogger(__name__)


async def complete(
    prompt: str,
    system: str = "",
    model: str | None = None,
) -> str:
    """
    Send a generation request to Google Gemini.
    Returns the model's reply as a plain string.

    Args:
        prompt: The user message.
        system: Optional system prompt (passed as system_instruction).
        model:  Gemini model name. Defaults to settings.gemini_model.
    """
    settings = get_settings()
    model = model or settings.gemini_model

    logger.debug("Gemini complete | model=%s | prompt_len=%d", model, len(prompt))

    client = genai.Client(api_key=settings.gemini_api_key)

    config = types.GenerateContentConfig(
        system_instruction=system if system else None,
    )

    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=config,
    )

    text = response.text or ""
    logger.debug("Gemini complete | response_len=%d", len(text))
    return text