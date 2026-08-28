"""Central configuration: env loading, model choice, and cost/safety budgets.

Every numeric limit here exists to keep this system cheap and safe to run
against a free-tier LLM key and a shared warehouse: nothing here is
decorative, each is referenced by the guardrail or loop code that enforces it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Config:
    gemini_api_key: str
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

    warehouse_path: Path = PROJECT_ROOT / "warehouse.db"
    runs_dir: Path = PROJECT_ROOT / "runs"

    # Investigation loop budget (bounds LLM call count per investigation).
    max_iterations: int = 6
    max_hypotheses: int = 5

    # SQL tool guardrails.
    max_rows_returned: int = 200
    query_timeout_seconds: float = 5.0
    allowed_tables: tuple[str, ...] = ("orders", "pipeline_runs", "schema_changes")

    # Context truncation fed back into the LLM, to keep token usage low.
    max_cell_chars: int = 200
    max_rows_in_prompt: int = 20

    # LLM retry/backoff for free-tier rate limits.
    max_retries: int = 5
    initial_backoff_seconds: float = 2.0

    # Anomaly detection: z-score against the same weekday's trailing values
    # (not a flat trailing window), since weekday seasonality would otherwise
    # swamp the signal for a metric with a strong weekly pattern.
    lookback_weeks: int = 8
    zscore_threshold: float = 4.0


def load_config() -> Config:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Add it to .env in the project root."
        )
    return Config(gemini_api_key=api_key)
