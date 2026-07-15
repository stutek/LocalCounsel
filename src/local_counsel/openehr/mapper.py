"""Map BIA measurements into openEHR-style compositions.

This is the **Mapper** half of the sync engine (see
``docs/longevity-coach/health-integration-architecture.md`` §4). It translates a
:class:`~local_counsel.health_sync.mock_google.BiaMeasurement` into a canonical
openEHR *Composition* dict built from published archetypes (body weight, BMI, and
a body-composition cluster for fat/muscle/water).

Two notes on scope:

* This produces a **canonical/minimal** composition — recognizable archetype and
  element paths with magnitudes and units — not a fully OPT-validated document.
  A validation gate against an Operational Template is future work (§7).
* Each composition carries a deterministic **UUIDv5** derived from a stable
  ``source_id`` (vendor + measurement time), giving idempotent re-sync: writing
  the same reading twice targets the same UID.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ..health_sync.mock_google import BiaMeasurement

# Fixed namespace for deterministic composition UIDs (UUIDv5). Stable forever.
UID_NAMESPACE = uuid.UUID("6f1c9d2e-3b7a-5e41-9c8f-2a1b0d4e5f60")

COMPOSITION_ARCHETYPE = "openEHR-EHR-COMPOSITION.encounter.v1"


def bia_source_id(measurement: BiaMeasurement, *, vendor: str = "bia-scale") -> str:
    """Stable source identifier for a reading — vendor + ISO measurement time."""
    return f"{vendor}:{measurement.measured_at.isoformat()}"


def composition_uid(source_id: str) -> str:
    """Deterministic UUIDv5 for a source record — the idempotency key."""
    return str(uuid.uuid5(UID_NAMESPACE, source_id))


def _element(archetype: str, name: str, magnitude: float, units: str, time: str) -> dict[str, Any]:
    return {
        "archetype_node_id": archetype,
        "name": name,
        # openEHR OBSERVATION event time — when THIS value was measured. Recorded
        # per element so each observation is self-contained rather than relying on
        # the composition context. ISO 8601, matching openEHR DV_DATE_TIME.
        "time": time,
        "value": {"magnitude": magnitude, "units": units},
    }


def bia_to_composition(
    measurement: BiaMeasurement,
    *,
    subject_id: str = "local-user",
    vendor: str = "bia-scale",
) -> dict[str, Any]:
    """Translate one BIA reading into a canonical openEHR composition dict.

    Only the measurements actually present are emitted as elements — a sparse real
    export (weight + body fat) yields a smaller composition than a full BIA panel.
    """
    source_id = bia_source_id(measurement, vendor=vendor)
    effective_time = measurement.measured_at.isoformat()

    # (archetype, name, value, units) — value None means "absent, skip".
    specs: list[tuple[str, str, float | None, str]] = [
        ("openEHR-EHR-OBSERVATION.body_weight.v2", "Body weight", measurement.weight_kg, "kg"),
        ("openEHR-EHR-OBSERVATION.body_mass_index.v2", "Body mass index", measurement.bmi, "kg/m2"),
        ("openEHR-EHR-OBSERVATION.body_composition.v0#body_fat", "Body fat percentage", measurement.body_fat_pct, "%"),
        ("openEHR-EHR-OBSERVATION.body_composition.v0#skeletal_muscle", "Skeletal muscle mass", measurement.skeletal_muscle_mass_kg, "kg"),
        ("openEHR-EHR-OBSERVATION.body_composition.v0#body_water", "Total body water percentage", measurement.body_water_pct, "%"),
        ("openEHR-EHR-OBSERVATION.body_composition.v0#bone_mass", "Bone mass", measurement.bone_mass_kg, "kg"),
        ("openEHR-EHR-OBSERVATION.basal_metabolic_rate.v0", "Basal metabolic rate", measurement.basal_metabolic_rate_kcal, "kcal/d"),
        (
            "openEHR-EHR-OBSERVATION.body_composition.v0#visceral_fat",
            "Visceral fat rating",
            None if measurement.visceral_fat_rating is None else float(measurement.visceral_fat_rating),
            "1",
        ),
    ]

    return {
        "uid": composition_uid(source_id),
        "archetype_node_id": COMPOSITION_ARCHETYPE,
        "name": "Body composition (BIA)",
        "source_id": source_id,
        "composer": {"subject_id": subject_id, "vendor": vendor},
        "context": {"start_time": effective_time},
        "content": [_element(a, n, v, u, effective_time) for a, n, v, u in specs if v is not None],
    }


def composition_to_measurement(composition: dict[str, Any]) -> BiaMeasurement:
    """Inverse of :func:`bia_to_composition` — reconstruct the reading.

    Lets the store act as the source of truth: read a composition back out of the
    encrypted repository and recover the original :class:`BiaMeasurement`.
    """
    by_node = {el["archetype_node_id"]: el["value"]["magnitude"] for el in composition["content"]}
    measured_at = datetime.fromisoformat(composition["context"]["start_time"])
    visceral = by_node.get("openEHR-EHR-OBSERVATION.body_composition.v0#visceral_fat")
    return BiaMeasurement(
        measured_at=measured_at,
        weight_kg=by_node["openEHR-EHR-OBSERVATION.body_weight.v2"],
        bmi=by_node.get("openEHR-EHR-OBSERVATION.body_mass_index.v2"),
        body_fat_pct=by_node.get("openEHR-EHR-OBSERVATION.body_composition.v0#body_fat"),
        skeletal_muscle_mass_kg=by_node.get("openEHR-EHR-OBSERVATION.body_composition.v0#skeletal_muscle"),
        body_water_pct=by_node.get("openEHR-EHR-OBSERVATION.body_composition.v0#body_water"),
        bone_mass_kg=by_node.get("openEHR-EHR-OBSERVATION.body_composition.v0#bone_mass"),
        basal_metabolic_rate_kcal=by_node.get("openEHR-EHR-OBSERVATION.basal_metabolic_rate.v0"),
        visceral_fat_rating=None if visceral is None else int(visceral),
    )
