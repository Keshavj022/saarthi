"""Thin Claude (Anthropic) client wrapper for Saarthi's reasoning layer.

Centralises model construction (one place reads the key from settings) and offers
three entry points used across the agents:

  * `chat()`        — free-text completion,
  * `structured()`  — completion forced into a pydantic schema (reliable parsing),
  * `render_in_language()` — render text into an Indian language (Phase 4).

Raises `LLMNotConfigured` with a clear message if the API key is absent, so
callers (scripts) can fail gracefully instead of deep inside langchain.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Type, TypeVar

from pydantic import BaseModel

from config.settings import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Anthropic requires an explicit output cap. The reasoning layer emits compact
# structured verdicts and short advisories, so this is generous headroom.
_MAX_TOKENS = 2048


class LLMNotConfigured(RuntimeError):
    """Raised when the reasoning-layer API key is not configured."""


class LLMError(RuntimeError):
    """An AI call failed (quota, billing, bad key, etc.) — clean message."""


@lru_cache(maxsize=1)
def _client():
    if not settings.anthropic_api_key:
        raise LLMNotConfigured(
            "ANTHROPIC_API_KEY is not set. Add it to .env (see .env.example) to use "
            "the reasoning layer."
        )
    from langchain_anthropic import ChatAnthropic

    # No temperature / top_p / top_k — the default model (Claude Opus 4.x) rejects
    # sampling parameters. Behaviour is steered through the prompts instead.
    return ChatAnthropic(
        model=settings.anthropic_model.strip(),
        api_key=settings.anthropic_api_key,
        max_tokens=_MAX_TOKENS,
        max_retries=2,  # fail fast on hard errors (billing/quota) instead of long backoff
    )


def _invoke(runnable, messages):
    """Invoke a langchain runnable, translating provider errors into LLMError."""
    try:
        return runnable.invoke(messages)
    except (LLMNotConfigured, LLMError):
        raise
    except Exception as exc:  # external boundary: normalise provider errors
        text = str(exc)
        low = text.lower()
        if any(s in low for s in ("rate_limit", "429", "overloaded", "529", "credit", "billing")):
            raise LLMError(
                "The AI service is rate-limited or out of credits (HTTP 429). The key "
                "is valid, but there is no available quota — check the Anthropic "
                f"account's usage/billing, then retry. Current model: {settings.anthropic_model}."
            ) from exc
        if any(s in low for s in ("authentication", "permission", "401", "403", "invalid x-api-key", "invalid_api_key")):
            raise LLMError(
                "The AI service rejected the request — check ANTHROPIC_API_KEY / model "
                f"access. ({text[:150]})"
            ) from exc
        if "not_found" in low or "404" in low:
            raise LLMError(
                f"AI model '{settings.anthropic_model}' not found for this key. "
                f"Set ANTHROPIC_MODEL in .env to a model you can access."
            ) from exc
        raise LLMError(f"AI call failed: {text[:200]}") from exc


def _messages(prompt: str, system: str | None) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = []
    if system:
        msgs.append(("system", system))
    msgs.append(("human", prompt))
    return msgs


def chat(prompt: str, *, system: str | None = None, temperature: float = 0.2) -> str:
    """Free-text completion; returns the model's text.

    `temperature` is accepted for call-site compatibility but not forwarded — the
    default Claude model rejects sampling parameters.
    """
    response = _invoke(_client(), _messages(prompt, system))
    return response.content if hasattr(response, "content") else str(response)


def structured(prompt: str, schema: Type[T], *, system: str | None = None,
               temperature: float = 0.1) -> T:
    """Completion constrained to `schema`; returns a validated pydantic instance."""
    client = _client().with_structured_output(schema)
    return _invoke(client, _messages(prompt, system))


def render_in_language(text: str, language: str, *, temperature: float = 0.2) -> str:
    """Render `text` into `language` (e.g. 'Hindi') for authority-facing output."""
    system = (
        "You translate official traffic-authority communications. Render the "
        f"user's text in plain, natural {language} that a control-room operator "
        "or citizen would understand. Keep all numbers and place names accurate. "
        "Output only the translation — no preamble, no transliteration notes."
    )
    return chat(text, system=system, temperature=temperature)
