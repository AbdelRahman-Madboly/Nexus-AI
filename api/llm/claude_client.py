"""
api/llm/claude_client.py
========================
Async Anthropic / Claude client for Nexus-AI.

Uses the official `anthropic` SDK (AsyncAnthropic).
This file is ONLY imported by llm_router.py — never by feature code directly.

Functions:
  complete(prompt, system, model) → str
"""

import logging

from anthropic import AsyncAnthropic

from api.config import get_settings

logger = logging.getLogger(__name__)

# Current non-deprecated model — update here when Anthropic releases new versions
_DEFAULT_MODEL = "claude-sonnet-4-5"


async def complete(
    prompt: str,
    system: str = "",
    model: str | None = None,
) -> str:
    """
    Send a message to Anthropic Claude.
    Returns the assistant's reply as a plain string.

    Args:
        prompt: The user message.
        system: Optional system prompt.
        model:  Claude model string. Defaults to _DEFAULT_MODEL (overrides settings
                only if settings still has the deprecated value).
    """
    settings = get_settings()
    configured = settings.claude_model
    deprecated = "claude-sonnet-4-20250514"
    model = model or (configured if configured != deprecated else _DEFAULT_MODEL)

    logger.debug("Claude complete | model=%s | prompt_len=%d", model, len(prompt))

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Anthropic SDK takes system as a top-level param, not inside messages
    kwargs = dict(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    if system:
        kwargs["system"] = system

    response = await client.messages.create(**kwargs)

    text = response.content[0].text
    logger.debug("Claude complete | response_len=%d", len(text))
    return text