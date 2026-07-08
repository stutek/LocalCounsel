"""Unit tests for the mock Google Health BIA connector — pure, no network."""

from __future__ import annotations

from datetime import datetime, timezone

from local_counsel.health_sync import (
    BiaMeasurement,
    MockGoogleHealthConnector,
    generate_bia_series,
)
from local_counsel.health_sync.mock_google import DATA_TYPE_WEIGHT, _NANOS_PER_SECOND

FIXED_END = datetime(2026, 7, 8, tzinfo=timezone.utc)


def test_default_yields_twelve_monthly_measurements():
    connector = MockGoogleHealthConnector(end_date=FIXED_END)
    series = connector.fetch_bia_measurements()
    assert len(series) == 12
    assert all(isinstance(m, BiaMeasurement) for m in series)


def test_series_is_oldest_first_and_monthly():
    series = generate_bia_series(12, end_date=FIXED_END)
    times = [m.measured_at for m in series]
    assert times == sorted(times)
    assert series[-1].measured_at == FIXED_END
    # ~30-day spacing between consecutive readings.
    for earlier, later in zip(series, series[1:]):
        assert (later.measured_at - earlier.measured_at).days == 30


def test_series_is_deterministic_for_seed():
    a = generate_bia_series(12, end_date=FIXED_END, seed=42)
    b = generate_bia_series(12, end_date=FIXED_END, seed=42)
    assert a == b
    assert generate_bia_series(12, end_date=FIXED_END, seed=99) != a


def test_values_are_physiologically_plausible():
    for m in generate_bia_series(12, end_date=FIXED_END):
        assert 40 < m.weight_kg < 200
        assert 3 < m.body_fat_pct < 60
        assert 10 < m.bmi < 60
        assert m.skeletal_muscle_mass_kg > 0
        assert 40 < m.body_water_pct < 75
        assert m.visceral_fat_rating >= 1


def test_recomposition_trend_fat_down_muscle_up():
    series = generate_bia_series(12, end_date=FIXED_END)
    assert series[-1].body_fat_pct < series[0].body_fat_pct
    assert series[-1].skeletal_muscle_mass_kg > series[0].skeletal_muscle_mass_kg


def test_raw_dataset_matches_google_fit_shape():
    connector = MockGoogleHealthConnector(end_date=FIXED_END)
    datasets = connector.fetch_raw_dataset()
    assert datasets, "expected at least one data stream"

    weight_ds = next(d for d in datasets if DATA_TYPE_WEIGHT in d["dataSourceId"])
    assert weight_ds["dataSourceId"].startswith("derived:")
    assert len(weight_ds["point"]) == 12

    point = weight_ds["point"][0]
    assert point["dataTypeName"] == DATA_TYPE_WEIGHT
    assert point["startTimeNanos"] == point["endTimeNanos"]
    assert "fpVal" in point["value"][0]
    # Nanosecond timestamp round-trips to the measurement time.
    parsed = generate_bia_series(12, end_date=FIXED_END)[0].measured_at
    assert int(point["startTimeNanos"]) == int(parsed.timestamp() * _NANOS_PER_SECOND)


def test_raw_visceral_fat_is_integer_valued():
    connector = MockGoogleHealthConnector(end_date=FIXED_END)
    datasets = connector.fetch_raw_dataset()
    visceral = next(d for d in datasets if "visceral_fat" in d["dataSourceId"])
    assert "intVal" in visceral["point"][0]["value"][0]


def test_custom_month_count():
    assert len(generate_bia_series(6, end_date=FIXED_END)) == 6
    assert len(generate_bia_series(1, end_date=FIXED_END)) == 1
