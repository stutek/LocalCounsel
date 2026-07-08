"""Unit tests for the BIA -> anonymized nutrition prompt logic — no network."""

from __future__ import annotations

import random
import re
from datetime import datetime, timezone

from local_counsel.health_sync import (
    SubjectProfile,
    ask_nutrition_advice,
    build_nutrition_prompt,
    generate_bia_series,
    summarize_fluctuations,
)

FIXED_END = datetime(2026, 7, 8, tzinfo=timezone.utc)
SERIES = generate_bia_series(12, end_date=FIXED_END)
PROFILE = SubjectProfile(sex="Male", age_years=42)


def test_summary_captures_all_four_metrics():
    s = summarize_fluctuations(SERIES)
    labels = [m.label for m in s.metrics()]
    assert labels == ["Weight", "Body fat", "Hydration (body water)", "Skeletal muscle"]
    assert s.months == 12


def test_summary_delta_swing_and_direction():
    s = summarize_fluctuations(SERIES)
    # Recomposition: fat trends down, muscle up (matches the mock series trend).
    assert s.body_fat.direction == "down"
    assert s.body_fat.delta < 0
    assert s.muscle.direction == "up"
    # Swing is peak-to-trough and never negative.
    for m in s.metrics():
        assert m.swing >= 0
        assert m.minimum <= m.start <= m.maximum
        assert m.minimum <= m.end <= m.maximum


def test_prompt_mentions_all_four_fluctuation_axes():
    prompt = build_nutrition_prompt(SERIES).lower()
    for axis in ("weight", "body-fat", "hydration", "muscle"):
        assert axis in prompt
    assert "nutrition" in prompt


def test_prompt_is_anonymized_no_dates_or_pii():
    prompt = build_nutrition_prompt(SERIES)
    # No calendar dates (ISO or year) may leak into the external payload.
    assert not re.search(r"\b20\d{2}\b", prompt)
    assert not re.search(r"\d{4}-\d{2}-\d{2}", prompt)
    # Timeline is expressed only as relative offsets.
    assert "current" in prompt
    assert "-11 mo" in prompt


def test_prompt_recommends_professional_oversight():
    prompt = build_nutrition_prompt(SERIES).lower()
    assert "professional" in prompt
    assert "do not diagnose" in prompt


def test_fuzzed_age_band_is_deterministic_and_excludes_exact_age():
    low, high = PROFILE.fuzzed_age_band()  # 42 ± round(42*0.15)=6 -> (36, 48)
    assert (low, high) == (36, 48)
    assert PROFILE.age_years not in (low, high)
    assert low < PROFILE.age_years < high


def test_fuzzed_age_band_randomised_shifts_centre_within_bounds():
    bands = {PROFILE.fuzzed_age_band(rng=random.Random(s)) for s in range(50)}
    assert len(bands) > 1  # random centre shift produces varied bands
    for low, high in bands:
        assert high - low == 12  # width stays 2*half (=12)


def test_prompt_includes_sex_and_fuzzed_age_band_not_exact_age():
    prompt = build_nutrition_prompt(SERIES, PROFILE)
    assert "Male" in prompt
    assert "age band ~36-48" in prompt
    assert "fuzzed" in prompt
    # The exact age must never appear as a standalone token.
    assert not re.search(r"(?<!\d)42(?!\d)", prompt)


def test_prompt_without_profile_is_unchanged_and_omits_demographics():
    prompt = build_nutrition_prompt(SERIES)
    assert "Subject:" not in prompt
    assert "age band" not in prompt


def test_profile_prompt_still_leaks_no_dates():
    prompt = build_nutrition_prompt(SERIES, PROFILE, rng=random.Random(1))
    assert not re.search(r"\d{4}-\d{2}-\d{2}", prompt)
    assert not re.search(r"\b20\d{2}\b", prompt)


def test_profile_json_roundtrip():
    assert SubjectProfile.from_dict(PROFILE.as_dict()) == PROFILE


def test_ask_nutrition_advice_wires_prompt_to_injected_model():
    captured = {}

    def fake_ask(prompt: str) -> str:
        captured["prompt"] = prompt
        return "Educational advice: prioritize protein and hydration."

    reply = ask_nutrition_advice(SERIES, ask=fake_ask)
    assert reply.startswith("Educational advice")
    # The model received the anonymized, fluctuation-aware prompt.
    assert "Net fluctuations" in captured["prompt"]
    assert not re.search(r"\d{4}-\d{2}-\d{2}", captured["prompt"])
