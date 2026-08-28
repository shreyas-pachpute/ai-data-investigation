"""Thin Gemini client wrapper: structured JSON output + retry/backoff.

Every call site passes a pydantic model as response_schema and gets one
back via resp.parsed — this is the mechanism behind "every boundary between
an LLM step and the rest of the system is a typed structured output"
(RESEARCH_NOTES.md Section 3). Retry/backoff exists specifically because
this project runs on a free-tier key with low rate limits (the user's
explicit cost/limit constraint), so a transient 429 should not abort an
otherwise-working investigation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from investigator.config import Config

# google-genai logs a one-time "use Chat instead of generate_content" notice
# that's irrelevant here (we never use automatic function calling) and only
# clutters CLI output.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

T = TypeVar("T", bound=BaseModel)


class DailyQuotaExhausted(Exception):
    """Raised when the free-tier per-day request quota is exhausted.

    Deliberately NOT retried: a 429 caused by a daily (not per-minute) quota
    will not resolve within any reasonable backoff window, so retrying just
    burns additional request attempts against an already-exhausted budget.
    """


def _is_daily_quota_error(exc: errors.APIError) -> bool:
    details = getattr(exc, "details", None) or {}
    error_body = details.get("error", details) if isinstance(details, dict) else {}
    for item in error_body.get("details", []) if isinstance(error_body, dict) else []:
        for violation in item.get("violations", []):
            if "PerDay" in str(violation.get("quotaId", "")):
                return True
    return "PerDay" in str(details)


@dataclass
class LLMCallStats:
    call_count: int = 0
    total_prompt_tokens: int = 0
    total_output_tokens: int = 0

    def record(self, prompt_tokens: int, output_tokens: int) -> None:
        self.call_count += 1
        self.total_prompt_tokens += prompt_tokens or 0
        self.total_output_tokens += output_tokens or 0


class GeminiClient:
    def __init__(self, config: Config):
        self._config = config
        self._client = genai.Client(api_key=config.gemini_api_key)
        self.stats = LLMCallStats()

    def generate_structured(
        self, system_instruction: str, user_prompt: str, response_model: type[T]
    ) -> T:
        backoff = self._config.initial_backoff_seconds
        last_error: Exception | None = None

        for attempt in range(self._config.max_retries):
            try:
                resp = self._client.models.generate_content(
                    model=self._config.gemini_model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=response_model,
                        temperature=0.2,
                    ),
                )
                usage = resp.usage_metadata
                self.stats.record(
                    prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                    output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                )
                if resp.parsed is None:
                    raise ValueError(f"Model did not return parseable JSON: {resp.text!r}")
                return resp.parsed
            except errors.APIError as exc:
                last_error = exc
                if getattr(exc, "code", None) == 429 and _is_daily_quota_error(exc):
                    raise DailyQuotaExhausted(
                        "Free-tier daily request quota exhausted for "
                        f"model '{self._config.gemini_model}'. This will not "
                        "resolve by retrying — wait for the daily quota reset "
                        f"or switch GEMINI_MODEL. Original error: {exc}"
                    ) from exc
                is_retryable = getattr(exc, "code", None) in (429, 500, 503)
                if not is_retryable or attempt == self._config.max_retries - 1:
                    raise
                time.sleep(backoff)
                backoff *= 2

        raise last_error  # pragma: no cover — loop always returns or raises above
