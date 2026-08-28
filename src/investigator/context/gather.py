"""Deterministic context gathering — runs once, before the agent loop starts.

PROJECT.md Section 11: the metric-catalog definition is a "Resource loaded
deterministically at the start of an investigation," not something the
agent queries iteratively. This module assembles that starting context:
the metric's authoritative definition, its recent value history, and the
pipeline-run window around the anomaly date — known, structured facts, not
reasoning (Section 5).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from investigator.config import Config
from investigator.detection.anomaly import AnomalyResult, evaluate_date


@dataclass
class InvestigationContext:
    metric_name: str
    metric_definition: str
    metric_owner: str
    anomaly: AnomalyResult
    recent_values: list[tuple[str, float]]  # last 14 days, (date, value)
    pipeline_runs_window: list[tuple]  # (run_id, pipeline_name, run_date, status, rows_processed, error_message)
    schema_changes_window: list[tuple]  # (change_id, table_name, change_date, description)


def gather_context(config: Config, target_date: str, metric_name: str = "daily_revenue") -> InvestigationContext:
    conn = sqlite3.connect(config.warehouse_path)
    try:
        cat_row = conn.execute(
            "SELECT definition, owner FROM metrics_catalog WHERE metric_name = ?",
            (metric_name,),
        ).fetchone()
        if cat_row is None:
            raise ValueError(f"Unknown metric '{metric_name}' — not in metrics_catalog.")
        definition, owner = cat_row

        anomaly = evaluate_date(config, target_date)

        target = date.fromisoformat(target_date)
        window_start = (target - timedelta(days=14)).isoformat()
        recent_rows = conn.execute(
            "SELECT order_date, SUM(revenue) FROM orders "
            "WHERE order_date BETWEEN ? AND ? GROUP BY order_date ORDER BY order_date",
            (window_start, target_date),
        ).fetchall()

        pipeline_window_start = (target - timedelta(days=3)).isoformat()
        pipeline_rows = conn.execute(
            "SELECT run_id, pipeline_name, run_date, status, rows_processed, error_message "
            "FROM pipeline_runs WHERE run_date BETWEEN ? AND ? ORDER BY run_date",
            (pipeline_window_start, target_date),
        ).fetchall()

        schema_window_start = (target - timedelta(days=14)).isoformat()
        schema_rows = conn.execute(
            "SELECT change_id, table_name, change_date, description "
            "FROM schema_changes WHERE change_date BETWEEN ? AND ? ORDER BY change_date",
            (schema_window_start, target_date),
        ).fetchall()

        return InvestigationContext(
            metric_name=metric_name,
            metric_definition=definition,
            metric_owner=owner,
            anomaly=anomaly,
            recent_values=[(r[0], r[1]) for r in recent_rows],
            pipeline_runs_window=pipeline_rows,
            schema_changes_window=schema_rows,
        )
    finally:
        conn.close()
