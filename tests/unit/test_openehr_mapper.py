"""Unit tests for the BIA <-> openEHR composition mapper — pure, no network."""

from __future__ import annotations

from datetime import datetime, timezone

from local_counsel.health_sync import generate_bia_series
from local_counsel.openehr.mapper import (
    bia_to_composition,
    composition_to_measurement,
    composition_uid,
)

FIXED_END = datetime(2026, 7, 8, tzinfo=timezone.utc)


def test_composition_has_uid_and_expected_archetypes():
    comp = bia_to_composition(generate_bia_series(1, end_date=FIXED_END)[0])
    assert comp["uid"]
    nodes = {el["archetype_node_id"] for el in comp["content"]}
    assert "openEHR-EHR-OBSERVATION.body_weight.v2" in nodes
    assert "openEHR-EHR-OBSERVATION.body_mass_index.v2" in nodes
    assert len(comp["content"]) == 8


def test_uid_is_deterministic_and_time_specific():
    series = generate_bia_series(2, end_date=FIXED_END)
    a = bia_to_composition(series[0])["uid"]
    again = bia_to_composition(series[0])["uid"]
    other = bia_to_composition(series[1])["uid"]
    assert a == again          # same reading -> same UID (idempotency key)
    assert a != other          # different reading -> different UID
    assert a == composition_uid(bia_to_composition(series[0])["source_id"])


def test_roundtrips_back_to_measurement():
    for m in generate_bia_series(12, end_date=FIXED_END):
        assert composition_to_measurement(bia_to_composition(m)) == m
