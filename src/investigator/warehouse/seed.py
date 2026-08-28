"""Synthetic warehouse generator with four ground-truth-labeled incidents.

Each injected incident maps to one of the hypothesis categories named in
PROJECT.md Section 5/21 (data-quality, genuine business change, seasonality,
definitional/schema change). These four dates ARE the eval suite's ground
truth (see eval/incidents.py) — the generator and the eval labels must stay
in sync, which is why the incident dates live here as the single source of
truth and are imported wherever they're needed.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from investigator.config import Config

START_DATE = date(2025, 1, 1)
END_DATE = date(2026, 3, 31)

REGIONS = {"NA": 0.45, "EMEA": 0.30, "APAC": 0.25}
SEGMENTS = {"Enterprise": 0.50, "SMB": 0.30, "Consumer": 0.20}
CHANNELS = {"Web": 0.60, "Mobile": 0.25, "Partner": 0.15}

BASE_DAILY_REVENUE = 100_000.0
ANNUAL_GROWTH = 0.30  # cumulative trend growth across the whole period
DAY_NOISE_STD = 0.04
COMBO_NOISE_STD = 0.03

INCIDENT_PIPELINE_FAILURE_DATE = date(2025, 4, 15)
INCIDENT_GENUINE_SPIKE_DATE = date(2025, 7, 8)
INCIDENT_SEASONAL_DATE = date(2025, 11, 28)  # Black Friday 2025
INCIDENT_DEFINITIONAL_CHANGE_DATE = date(2026, 2, 10)

WEEKDAY_MULTIPLIER = {0: 1.05, 1: 1.05, 2: 1.05, 3: 1.05, 4: 1.0, 5: 0.65, 6: 0.60}

RNG_SEED = 42


@dataclass
class SeedSummary:
    orders_rows: int
    pipeline_runs_rows: int
    schema_changes_rows: int
    date_range: tuple[str, str]


def _daily_trend_multiplier(d: date) -> float:
    days_elapsed = (d - START_DATE).days
    total_days = (END_DATE - START_DATE).days
    return 1.0 + ANNUAL_GROWTH * (days_elapsed / total_days)


def _iter_dates():
    d = START_DATE
    while d <= END_DATE:
        yield d
        d += timedelta(days=1)


def _generate_orders(rng: random.Random) -> list[tuple]:
    rows: list[tuple] = []
    order_id = 1
    for d in _iter_dates():
        day_target = (
            BASE_DAILY_REVENUE
            * _daily_trend_multiplier(d)
            * WEEKDAY_MULTIPLIER[d.weekday()]
            * (1.0 + rng.gauss(0, DAY_NOISE_STD))
        )

        definitional_uplift = 1.15 if d >= INCIDENT_DEFINITIONAL_CHANGE_DATE else 1.0

        for region, region_share in REGIONS.items():
            for segment, segment_share in SEGMENTS.items():
                for channel, channel_share in CHANNELS.items():
                    combo_revenue = day_target * region_share * segment_share * channel_share

                    if d == INCIDENT_PIPELINE_FAILURE_DATE and region == "NA":
                        combo_revenue *= 0.08  # near-total ingestion loss for NA that day

                    if (
                        d == INCIDENT_GENUINE_SPIKE_DATE
                        and region == "EMEA"
                        and segment == "Consumer"
                    ):
                        combo_revenue *= 4.5  # targeted flash-sale spike

                    if d == INCIDENT_SEASONAL_DATE:
                        combo_revenue *= 2.3  # broad-based Black Friday lift

                    combo_revenue *= definitional_uplift
                    combo_revenue *= 1.0 + rng.gauss(0, COMBO_NOISE_STD)
                    combo_revenue = max(combo_revenue, 0.0)

                    unit_price = round(rng.uniform(35, 180), 2)
                    quantity = max(1, round(combo_revenue / unit_price))
                    actual_revenue = round(quantity * unit_price, 2)

                    rows.append(
                        (
                            order_id,
                            d.isoformat(),
                            region,
                            segment,
                            channel,
                            quantity,
                            unit_price,
                            actual_revenue,
                        )
                    )
                    order_id += 1
    return rows


def _generate_pipeline_runs(rng: random.Random) -> list[tuple]:
    rows: list[tuple] = []
    run_id = 1
    for d in _iter_dates():
        if d == INCIDENT_PIPELINE_FAILURE_DATE:
            rows.append(
                (
                    run_id,
                    "orders_ingest_na",
                    d.isoformat(),
                    "failed",
                    143,
                    "connection timeout to source DB after partial batch; "
                    "NA region batch incomplete",
                )
            )
            run_id += 1
            rows.append((run_id, "orders_ingest_emea", d.isoformat(), "success", 3210, None))
            run_id += 1
            rows.append((run_id, "orders_ingest_apac", d.isoformat(), "success", 2877, None))
            run_id += 1
        else:
            rows.append(
                (
                    run_id,
                    "orders_ingest_all_regions",
                    d.isoformat(),
                    "success",
                    rng.randint(2800, 3600),
                    None,
                )
            )
            run_id += 1
    return rows


def _generate_schema_changes() -> list[tuple]:
    return [
        (
            1,
            "orders",
            "2025-02-03",
            "Added 'channel' column with backfilled default 'Web' for pre-2025 "
            "historical rows; no impact on revenue values.",
        ),
        (
            2,
            "orders",
            "2025-09-01",
            "Renamed internal ETL staging column 'amt' to 'revenue' during a "
            "warehouse migration; no change to computed values.",
        ),
        (
            3,
            "orders",
            INCIDENT_DEFINITIONAL_CHANGE_DATE.isoformat(),
            "unit_price now includes shipping fee in addition to item price "
            "(previously item price only), per finance request FIN-2201. "
            "This increases reported revenue per order by roughly 15% going "
            "forward; it is a definitional change, not a business change.",
        ),
    ]


def _generate_metrics_catalog() -> list[tuple]:
    return [
        (
            "daily_revenue",
            "SUM(orders.revenue) grouped by orders.order_date across all "
            "regions, segments, and channels unless explicitly filtered. "
            "revenue = quantity * unit_price per order row.",
            "finance-analytics",
        )
    ]


def build_warehouse(config: Config) -> SeedSummary:
    rng = random.Random(RNG_SEED)

    config.warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    if config.warehouse_path.exists():
        config.warehouse_path.unlink()

    conn = sqlite3.connect(config.warehouse_path)
    try:
        schema_sql = (Path(__file__).parent / "schema.sql").read_text()
        conn.executescript(schema_sql)

        orders = _generate_orders(rng)
        pipeline_runs = _generate_pipeline_runs(rng)
        schema_changes = _generate_schema_changes()
        metrics_catalog = _generate_metrics_catalog()

        conn.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", orders
        )
        conn.executemany(
            "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?)", pipeline_runs
        )
        conn.executemany(
            "INSERT INTO schema_changes VALUES (?, ?, ?, ?)", schema_changes
        )
        conn.executemany(
            "INSERT INTO metrics_catalog VALUES (?, ?, ?)", metrics_catalog
        )
        conn.commit()

        return SeedSummary(
            orders_rows=len(orders),
            pipeline_runs_rows=len(pipeline_runs),
            schema_changes_rows=len(schema_changes),
            date_range=(START_DATE.isoformat(), END_DATE.isoformat()),
        )
    finally:
        conn.close()
