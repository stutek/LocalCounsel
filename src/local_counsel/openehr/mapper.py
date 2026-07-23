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
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from ..health_sync.mock_google import BiaMeasurement

# Fixed namespace for deterministic composition UIDs (UUIDv5). Stable forever.
UID_NAMESPACE = uuid.UUID("6f1c9d2e-3b7a-5e41-9c8f-2a1b0d4e5f60")

COMPOSITION_ARCHETYPE = "openEHR-EHR-COMPOSITION.encounter.v1"

# Archetype paths used by this deliberately small, openEHR-*style* composition.
# Keeping them in one table makes the mapping easy to audit: every BIA input has
# one output path, a human-facing label, and a unit.
BODY_WEIGHT = "openEHR-EHR-OBSERVATION.body_weight.v2"
BODY_MASS_INDEX = "openEHR-EHR-OBSERVATION.body_mass_index.v2"
BODY_FAT = "openEHR-EHR-OBSERVATION.body_composition.v0#body_fat"
SKELETAL_MUSCLE = "openEHR-EHR-OBSERVATION.body_composition.v0#skeletal_muscle"
BODY_WATER = "openEHR-EHR-OBSERVATION.body_composition.v0#body_water"
BONE_MASS = "openEHR-EHR-OBSERVATION.body_composition.v0#bone_mass"
BASAL_METABOLIC_RATE = "openEHR-EHR-OBSERVATION.basal_metabolic_rate.v0"
VISCERAL_FAT = "openEHR-EHR-OBSERVATION.body_composition.v0#visceral_fat"


@dataclass(frozen=True)
class BiaElementSpec:
    """The contract for mapping one ``BiaMeasurement`` field to one element."""

    measurement_field: str
    archetype_path: str
    label: str
    units: str
    convert: Callable[[float | int], float] = float


BIA_ELEMENT_SPECS: tuple[BiaElementSpec, ...] = (
    BiaElementSpec("weight_kg", BODY_WEIGHT, "Body weight", "kg"),
    BiaElementSpec("bmi", BODY_MASS_INDEX, "Body mass index", "kg/m2"),
    BiaElementSpec("body_fat_pct", BODY_FAT, "Body fat percentage", "%"),
    BiaElementSpec("skeletal_muscle_mass_kg", SKELETAL_MUSCLE, "Skeletal muscle mass", "kg"),
    BiaElementSpec("body_water_pct", BODY_WATER, "Total body water percentage", "%"),
    BiaElementSpec("bone_mass_kg", BONE_MASS, "Bone mass", "kg"),
    BiaElementSpec("basal_metabolic_rate_kcal", BASAL_METABOLIC_RATE, "Basal metabolic rate", "kcal/d"),
    BiaElementSpec("visceral_fat_rating", VISCERAL_FAT, "Visceral fat rating", "1"),
)


def bia_source_id(measurement: BiaMeasurement, *, vendor: str) -> str:
    """Build an idempotency source ID from a connector-supplied vendor identifier.

    ``vendor`` is intentionally required: the mapper must not guess the source
    system because two devices can record a measurement at the same instant.
    """
    return f"{vendor}:{measurement.measured_at.isoformat()}"


def composition_uid(source_id: str) -> str:
    """Deterministic UUIDv5 for a source record — the idempotency key."""
    return str(uuid.uuid5(UID_NAMESPACE, source_id))


def _element(spec: BiaElementSpec, magnitude: float, time: str) -> dict[str, Any]:
    """Build the repeated element shape used inside this composition."""
    return {
        "archetype_node_id": spec.archetype_path,
        "name": spec.label,
        # openEHR OBSERVATION event time — when THIS value was measured. Recorded
        # per element so each observation is self-contained rather than relying on
        # the composition context. ISO 8601, matching openEHR DV_DATE_TIME.
        "time": time,
        "value": {"magnitude": magnitude, "units": spec.units},
    }


def _mapped_elements(measurement: BiaMeasurement, effective_time: str) -> list[dict[str, Any]]:
    """Map present BIA fields; optional source values are intentionally omitted."""
    elements = []
    for spec in BIA_ELEMENT_SPECS:
        source_value = getattr(measurement, spec.measurement_field)
        if source_value is not None:
            elements.append(_element(spec, spec.convert(source_value), effective_time))
    return elements


def bia_to_composition(
    measurement: BiaMeasurement,
    *,
    subject_id: str = "local-user",
    vendor: str,
) -> dict[str, Any]:
    """Translate one BIA reading into a canonical openEHR composition dict.

    ``vendor`` is the stable identifier supplied by the connector (for example,
    a device or source-system identifier). Only measurements actually present are
    emitted as elements — a sparse real export (weight + body fat) yields a smaller
    composition than a full BIA panel.
    """
    source_id = bia_source_id(measurement, vendor=vendor)
    effective_time = measurement.measured_at.isoformat()

    return {
        "uid": composition_uid(source_id),
        "archetype_node_id": COMPOSITION_ARCHETYPE,
        "name": "Body composition (BIA)",
        "source_id": source_id,
        "composer": {"subject_id": subject_id, "vendor": vendor},
        "context": {"start_time": effective_time},
        "content": _mapped_elements(measurement, effective_time),
    }


def composition_to_measurement(composition: dict[str, Any]) -> BiaMeasurement:
    """Inverse of :func:`bia_to_composition` — reconstruct the reading.

    Lets the store act as the source of truth: read a composition back out of the
    encrypted repository and recover the original :class:`BiaMeasurement`.
    """
    values_by_path = {
        element["archetype_node_id"]: element["value"]["magnitude"]
        for element in composition["content"]
    }
    measured_at = datetime.fromisoformat(composition["context"]["start_time"])
    return BiaMeasurement(
        measured_at=measured_at,
        weight_kg=values_by_path[BODY_WEIGHT],
        bmi=values_by_path.get(BODY_MASS_INDEX),
        body_fat_pct=values_by_path.get(BODY_FAT),
        skeletal_muscle_mass_kg=values_by_path.get(SKELETAL_MUSCLE),
        body_water_pct=values_by_path.get(BODY_WATER),
        bone_mass_kg=values_by_path.get(BONE_MASS),
        basal_metabolic_rate_kcal=values_by_path.get(BASAL_METABOLIC_RATE),
        visceral_fat_rating=(
            None if VISCERAL_FAT not in values_by_path else int(values_by_path[VISCERAL_FAT])
        ),
    )
