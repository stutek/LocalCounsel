"""Unit test verifying the anonymized Beurer BIA 7-month test fixture."""

from __future__ import annotations

import json
from pathlib import Path

from local_counsel.health_sync.nutrition import SubjectProfile, build_nutrition_prompt
from local_counsel.health_sync.mock_google import BiaMeasurement
from datetime import datetime, timezone

DATA_FILE = Path(__file__).parent.parent / "data" / "anonymized_beurer_bia_7m.json"


def test_anonymized_beurer_bia_fixture_loads_without_pii():
    assert DATA_FILE.exists(), f"Fixture file not found at {DATA_FILE}"
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    # Verify no PII fields exist
    profile_data = payload["subject_profile_fuzzed"]
    assert "name" not in profile_data
    assert "age_years" not in profile_data
    assert profile_data["fuzzed_age_band"] == "~38-46"

    readings = payload["readings"]
    assert len(readings) == 7

    # Verify all relative month labels and values
    assert readings[0]["relative_month"] == "-6 mo"
    assert readings[-1]["relative_month"] == "current"

    # Convert to BiaMeasurement sequence and build prompt
    series = []
    for idx, r in enumerate(readings):
        meas = BiaMeasurement(
            measured_at=datetime(2026, idx + 1, 1, tzinfo=timezone.utc),
            weight_kg=r["weight_kg"],
            bmi=r["bmi"],
            body_fat_pct=r["body_fat_pct"],
            skeletal_muscle_mass_kg=r["skeletal_muscle_mass_kg"],
            body_water_pct=r["body_water_pct"],
            bone_mass_kg=r["bone_mass_kg"],
            basal_metabolic_rate_kcal=r["basal_metabolic_rate_kcal"],
            visceral_fat_rating=r["visceral_fat_rating"],
        )
        series.append(meas)

    profile = SubjectProfile(sex=profile_data["sex"], age_years=42)
    prompt = build_nutrition_prompt(series, profile)

    # Ensure generated prompt contains the randomized fuzzed age and no calendar dates
    assert "approx. age" in prompt
    assert "71.77 -> 71.34" in prompt
    assert "2026-" not in prompt
    assert "2025-" not in prompt
