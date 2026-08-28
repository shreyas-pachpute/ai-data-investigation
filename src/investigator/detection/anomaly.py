"""Deterministic anomaly detection — explicitly NOT an LLM step.

PROJECT.md Section 8: "Anomaly detection (is this metric outside its normal
statistical range) is a fixed computation, not agentic — this triggers the
investigation but isn't part of it." This module never calls an LLM and is
fully unit-testable.

Z-score is computed against the trailing occurrences of the SAME weekday
(not a flat trailing window) because daily revenue has a strong weekly
pattern (weekends run ~35-40% lighter) that would otherwise swamp any
genuine anomaly signal in a naive rolling mean/std.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from investigator.config import Config


@dataclass
class AnomalyResult:
    metric_date: str
    value: float
    baseline_mean: float
    baseline_std: float
    zscore: float
    is_anomaly: bool
    direction: str | None  # "spike", "drop", or None


def _load_daily_revenue_series(config: Config) -> dict[str, float]:
    conn = sqlite3.connect(config.warehouse_path)
    try:
        cursor = conn.execute(
            "SELECT order_date, SUM(revenue) FROM orders GROUP BY order_date ORDER BY order_date"
        )
        return {row[0]: row[1] for row in cursor.fetchall()}
    finally:
        conn.close()


def _same_weekday_baseline(
    series: dict[str, float], target: date, lookback_weeks: int
) -> list[float]:
    values = []
    for i in range(1, lookback_weeks + 1):
        prior = (target - timedelta(weeks=i)).isoformat()
        if prior in series:
            values.append(series[prior])
    return values


def evaluate_date(config: Config, target_date: str, series: dict[str, float] | None = None) -> AnomalyResult:
    if series is None:
        series = _load_daily_revenue_series(config)

    target = date.fromisoformat(target_date)
    value = series.get(target_date, 0.0)
    baseline = _same_weekday_baseline(series, target, config.lookback_weeks)

    if len(baseline) < 3:
        return AnomalyResult(target_date, value, value, 0.0, 0.0, False, None)

    mean = statistics.mean(baseline)
    std = statistics.pstdev(baseline) if len(baseline) > 1 else 0.0
    std_floor = max(std, abs(mean) * 0.005, 1e-6)
    zscore = (value - mean) / std_floor

    is_anomaly = abs(zscore) >= config.zscore_threshold
    direction = None
    if is_anomaly:
        direction = "spike" if zscore > 0 else "drop"

    return AnomalyResult(target_date, value, mean, std, zscore, is_anomaly, direction)


def detect_all_anomalies(config: Config) -> list[AnomalyResult]:
    series = _load_daily_revenue_series(config)
    results = []
    for metric_date in sorted(series.keys()):
        result = evaluate_date(config, metric_date, series=series)
        if result.is_anomaly:
            results.append(result)
    return results
