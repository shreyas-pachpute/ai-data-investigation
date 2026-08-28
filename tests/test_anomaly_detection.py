from investigator.detection.anomaly import detect_all_anomalies, evaluate_date
from investigator.warehouse.seed import (
    INCIDENT_DEFINITIONAL_CHANGE_DATE,
    INCIDENT_GENUINE_SPIKE_DATE,
    INCIDENT_PIPELINE_FAILURE_DATE,
    INCIDENT_SEASONAL_DATE,
)


def test_pipeline_failure_date_flagged_as_drop(test_config):
    result = evaluate_date(test_config, INCIDENT_PIPELINE_FAILURE_DATE.isoformat())
    assert result.is_anomaly is True
    assert result.direction == "drop"


def test_genuine_spike_date_flagged_as_spike(test_config):
    result = evaluate_date(test_config, INCIDENT_GENUINE_SPIKE_DATE.isoformat())
    assert result.is_anomaly is True
    assert result.direction == "spike"


def test_seasonal_date_flagged_as_spike(test_config):
    result = evaluate_date(test_config, INCIDENT_SEASONAL_DATE.isoformat())
    assert result.is_anomaly is True
    assert result.direction == "spike"


def test_definitional_change_date_flagged(test_config):
    result = evaluate_date(test_config, INCIDENT_DEFINITIONAL_CHANGE_DATE.isoformat())
    assert result.is_anomaly is True


def test_ordinary_date_not_flagged(test_config):
    result = evaluate_date(test_config, "2025-03-04")
    assert result.is_anomaly is False


def test_detect_all_anomalies_includes_every_injected_incident(test_config):
    flagged_dates = {a.metric_date for a in detect_all_anomalies(test_config)}
    for expected in (
        INCIDENT_PIPELINE_FAILURE_DATE,
        INCIDENT_GENUINE_SPIKE_DATE,
        INCIDENT_SEASONAL_DATE,
        INCIDENT_DEFINITIONAL_CHANGE_DATE,
    ):
        assert expected.isoformat() in flagged_dates
