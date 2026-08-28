"""The curated historical-incident regression suite (PROJECT.md Section 17).

The ground truth here is defined by the warehouse generator itself
(warehouse/seed.py) — these four dates are exactly what was injected, so
this file imports the dates rather than restating them, keeping the
generator the single source of truth for what actually happened.
"""

from __future__ import annotations

from dataclasses import dataclass

from investigator.agent.schemas import RootCauseCategory
from investigator.warehouse.seed import (
    INCIDENT_DEFINITIONAL_CHANGE_DATE,
    INCIDENT_GENUINE_SPIKE_DATE,
    INCIDENT_PIPELINE_FAILURE_DATE,
    INCIDENT_SEASONAL_DATE,
)


@dataclass(frozen=True)
class GroundTruthIncident:
    incident_id: str
    target_date: str
    expected_category: RootCauseCategory
    description: str


CURATED_INCIDENTS: list[GroundTruthIncident] = [
    GroundTruthIncident(
        incident_id="pipeline_failure",
        target_date=INCIDENT_PIPELINE_FAILURE_DATE.isoformat(),
        expected_category=RootCauseCategory.DATA_QUALITY_ISSUE,
        description="NA region ingestion pipeline failed, dropping most NA orders for the day.",
    ),
    GroundTruthIncident(
        incident_id="genuine_spike",
        target_date=INCIDENT_GENUINE_SPIKE_DATE.isoformat(),
        expected_category=RootCauseCategory.GENUINE_BUSINESS_CHANGE,
        description="Targeted flash-sale spike concentrated in the EMEA/Consumer segment.",
    ),
    GroundTruthIncident(
        incident_id="seasonal_black_friday",
        target_date=INCIDENT_SEASONAL_DATE.isoformat(),
        expected_category=RootCauseCategory.SEASONAL_EXPECTED_VARIATION,
        description="Broad-based Black Friday lift applied proportionally across all regions/segments.",
    ),
    GroundTruthIncident(
        incident_id="definitional_change",
        target_date=INCIDENT_DEFINITIONAL_CHANGE_DATE.isoformat(),
        expected_category=RootCauseCategory.DEFINITIONAL_CHANGE,
        description="unit_price definition changed to include shipping fee — a permanent step change, not a business signal.",
    ),
]
