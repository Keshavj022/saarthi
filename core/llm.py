"""Thin Gemini client wrapper for Saarthi's reasoning layer.

Centralises model construction (one place reads the key from settings) and offers
three entry points used across the agents:

  * `chat()`        — free-text completion,
  * `structured()`  — completion forced into a pydantic schema (reliable parsing),
  * `render_in_language()` — render text into an Indian language (Phase 4).

Raises `LLMNotConfigured` with a clear message if the Gemini API key is absent,
so callers (scripts) can fail gracefully instead of deep inside langchain.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Type, TypeVar

from pydantic import BaseModel

from config.settings import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMNotConfigured(RuntimeError):
    """Raised when GEMINI_API_KEY is not configured."""


class LLMError(RuntimeError):
    """A Gemini API call failed (quota, billing, bad key, etc.) — clean message."""


def _normalize_model(name: str) -> str:
    """Accept friendly names like 'Gemini 2.5 Flash' -> API id 'gemini-2.5-flash'."""
    norm = name.strip().lower().replace(" ", "-")
    return norm.removeprefix("models/")


@lru_cache(maxsize=4)
def _client(temperature: float):
    if not settings.gemini_api_key:
        raise LLMNotConfigured(
            "GEMINI_API_KEY is not set. Add it to .env (see .env.example) to use "
            "the reasoning layer."
        )
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=_normalize_model(settings.gemini_model),
        google_api_key=settings.gemini_api_key,
        temperature=temperature,
        max_retries=2,  # fail fast on hard errors (billing/quota) instead of ~35s
    )


def _invoke(runnable, messages):
    """Invoke a langchain runnable, translating provider errors into LLMError."""
    try:
        return runnable.invoke(messages)
    except (LLMNotConfigured, LLMError):
        raise
    except Exception as exc:  # external boundary: normalise provider errors
        text = str(exc)
        if "RESOURCE_EXHAUSTED" in text or "429" in text:
            raise LLMError(
                "Gemini quota/credits exhausted (HTTP 429). The API key is valid, "
                "but the project has no available quota — enable billing / add "
                "credits in Google AI Studio, or use a key with free-tier quota. "
                f"Current model: {settings.gemini_model}."
            ) from exc
        if any(s in text for s in ("API_KEY_INVALID", "PERMISSION_DENIED", "401", "403")):
            raise LLMError(
                f"Gemini rejected the request — check GEMINI_API_KEY / model access. "
                f"({text[:150]})"
            ) from exc
        if "NOT_FOUND" in text or "404" in text:
            raise LLMError(
                f"Gemini model '{settings.gemini_model}' not found for this key. "
                f"Set GEMINI_MODEL in .env to a model you can access."
            ) from exc
        raise LLMError(f"Gemini call failed: {text[:200]}") from exc


def _messages(prompt: str, system: str | None) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = []
    if system:
        msgs.append(("system", system))
    msgs.append(("human", prompt))
    return msgs


def chat(prompt: str, *, system: str | None = None, temperature: float = 0.2) -> str:
    """Free-text completion; returns the model's text."""
    response = _invoke(_client(temperature), _messages(prompt, system))
    return response.content if hasattr(response, "content") else str(response)


def structured(prompt: str, schema: Type[T], *, system: str | None = None,
               temperature: float = 0.1) -> T:
    """Completion constrained to `schema`; returns a validated pydantic instance."""
    client = _client(temperature).with_structured_output(schema)
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
