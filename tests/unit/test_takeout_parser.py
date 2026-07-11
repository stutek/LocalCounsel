"""Unit tests for the Google Health / Beurer Takeout parser.

Uses a synthetic in-memory ZIP mirroring the real export schema — no private data.
"""

from __future__ import annotations

import io
import zipfile

from local_counsel.health_sync import parse_takeout_zip

_BASE = "Takeout/Google Health/Physical Activity_GoogleData"


def _zip(weight_rows: list[str], body_fat: dict[str, list[str]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{_BASE}/weight.csv", "timestamp,weight grams,data source\n" + "\n".join(weight_rows))
        for month, rows in body_fat.items():
            zf.writestr(
                f"{_BASE}/body_fat_{month}.csv",
                "timestamp,body fat percentage,data source\n" + "\n".join(rows),
            )
    return buf.getvalue()


SAMPLE = _zip(
    weight_rows=[
        "2025-06-10T06:00:00.1Z,75000,HealthManager Pro Health Connect",
        "2025-06-20T06:00:00.1Z,74000,Fitbit App",  # median of month -> 74.5 kg
        "2025-07-15T06:00:00.1Z,73000,HealthManager Pro Health Connect",
    ],
    body_fat={
        "2025-06-01": ["2025-06-12T06:00:00.1Z,19.0,HealthManager Pro Health Connect"],
        "2025-07-01": ["2025-07-15T06:00:00.1Z,18.4,HealthManager Pro Health Connect"],
    },
)


def test_parses_grams_to_kg_and_aggregates_monthly():
    series = parse_takeout_zip(SAMPLE, height_m=1.78)
    assert len(series) == 2  # June, July
    june, july = series
    assert june.weight_kg == 74.5  # median of 75.0 and 74.0
    assert june.body_fat_pct == 19.0
    assert june.bmi == round(74.5 / (1.78**2), 1)
    assert july.weight_kg == 73.0


def test_sparse_fields_are_none():
    m = parse_takeout_zip(SAMPLE)[0]
    assert m.skeletal_muscle_mass_kg is None
    assert m.body_water_pct is None
    assert m.visceral_fat_rating is None
    assert m.bmi is None  # no height given


def test_source_filter_selects_beurer_only():
    # June has one Beurer (75.0) and one Fitbit (74.0) weight; filter keeps Beurer.
    series = parse_takeout_zip(SAMPLE, source_contains="HealthManager Pro")
    june = series[0]
    assert june.weight_kg == 75.0  # only the Beurer reading survives the filter


def test_oldest_first_ordering():
    series = parse_takeout_zip(SAMPLE)
    assert [m.measured_at for m in series] == sorted(m.measured_at for m in series)
