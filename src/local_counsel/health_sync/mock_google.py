"""Mock Google Health retrieval for BIA (bioelectrical impedance) measurements.

BIA scales (Withings, Tanita, Xiaomi, ...) sync body-composition readings into
Google Fit. This module fakes that retrieval so the openEHR mapper, the Dify
workflow, and the Longevity Mentor analysis can be developed and tested offline —
no OAuth loopback, no ``fitness/v1`` calls, no real health data on disk.

It exposes the data two ways:

* :meth:`MockGoogleHealthConnector.fetch_bia_measurements` — parsed
  :class:`BiaMeasurement` domain objects, ready for the openEHR translator.
* :meth:`MockGoogleHealthConnector.fetch_raw_dataset` — the same series in the
  raw Google Fit ``users.dataSources.datasets.get`` response shape (nanosecond
  timestamps, ``point``/``value`` lists), so parsing code sees exactly the
  payload the live API would return.

The series is **deterministic** for a given seed and end date, so tests can
assert exact values and the idempotency logic (deterministic UUIDv5 per record)
stays reproducible across runs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# Google Fit data type names. Only weight and body-fat percentage are first-class
# Fit body-composition types; the richer BIA fields ride along as vendor streams
# under the ``com.google.body.*`` namespace, which is how scale apps surface them.
DATA_TYPE_WEIGHT = "com.google.weight"
DATA_TYPE_BODY_FAT = "com.google.body.fat.percentage"
DATA_TYPE_SKELETAL_MUSCLE = "com.google.body.muscle.mass"
DATA_TYPE_BODY_WATER = "com.google.body.water.percentage"
DATA_TYPE_BONE_MASS = "com.google.body.bone.mass"
DATA_TYPE_BMR = "com.google.body.basal_metabolic_rate"
DATA_TYPE_VISCERAL_FAT = "com.google.body.visceral_fat.rating"

# A plausible BIA scale app as the origin data source.
_ORIGIN_DATA_SOURCE = (
    "raw:com.google.weight:com.example.biascale:BIA-Smart-Scale"
)

_NANOS_PER_SECOND = 1_000_000_000


@dataclass(frozen=True)
class BiaMeasurement:
    """One bioelectrical-impedance body-composition reading.

    Field names mirror what a consumer BIA scale reports. ``bmi`` is derived from
    weight and height rather than measured, matching how the scale apps compute it.
    """

    # Only ``measured_at`` and ``weight_kg`` are guaranteed. Real Google Health /
    # Beurer (HealthManager Pro) exports carry just weight + body fat %, so every
    # richer BIA field is optional and may be ``None``.
    measured_at: datetime
    weight_kg: float
    body_fat_pct: float | None = None
    bmi: float | None = None
    skeletal_muscle_mass_kg: float | None = None
    body_water_pct: float | None = None
    bone_mass_kg: float | None = None
    basal_metabolic_rate_kcal: float | None = None
    visceral_fat_rating: int | None = None


def _round(value: float, ndigits: int = 1) -> float:
    return round(value, ndigits)


def generate_bia_series(
    months: int = 12,
    *,
    end_date: datetime | None = None,
    height_m: float = 1.78,
    start_weight_kg: float = 84.0,
    start_body_fat_pct: float = 26.0,
    seed: int = 20260708,
) -> list[BiaMeasurement]:
    """Generate ``months`` monthly BIA readings, oldest first.

    The trend models a realistic 12-month recomposition: gradual fat loss and a
    slight gain in skeletal muscle, with small month-to-month noise. Values are
    fully determined by ``seed`` and ``end_date`` for reproducible tests.

    The most recent reading lands on ``end_date`` (default: now, UTC); earlier
    readings step back one month (30 days) at a time.
    """
    if months < 1:
        raise ValueError("months must be >= 1")

    end_date = end_date or datetime.now(timezone.utc)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)

    rng = random.Random(seed)
    height_sq = height_m * height_m

    series: list[BiaMeasurement] = []
    # Index 0 is the oldest reading; progress runs 0.0 -> 1.0 towards the newest.
    for i in range(months):
        measured_at = end_date - timedelta(days=30 * (months - 1 - i))
        progress = i / (months - 1) if months > 1 else 1.0

        # Downward weight/fat drift with per-month jitter.
        weight = start_weight_kg - 6.5 * progress + rng.uniform(-0.6, 0.6)
        body_fat = start_body_fat_pct - 5.0 * progress + rng.uniform(-0.5, 0.5)

        fat_mass = weight * body_fat / 100.0
        lean_mass = weight - fat_mass
        # Skeletal muscle is roughly half of lean mass; nudge it up as fat drops.
        skeletal_muscle = lean_mass * 0.54 + 0.8 * progress + rng.uniform(-0.3, 0.3)
        body_water = 55.0 + 5.0 * progress + rng.uniform(-0.4, 0.4)
        bone_mass = 3.1 + rng.uniform(-0.05, 0.05)
        # Mifflin-St Jeor-ish resting energy, scaled by lean mass.
        bmr = 500 + 22.0 * lean_mass + rng.uniform(-25, 25)
        visceral_fat = round(12 - 4 * progress + rng.uniform(-0.5, 0.5))

        series.append(
            BiaMeasurement(
                measured_at=measured_at,
                weight_kg=_round(weight),
                bmi=_round(weight / height_sq),
                body_fat_pct=_round(body_fat),
                skeletal_muscle_mass_kg=_round(skeletal_muscle),
                body_water_pct=_round(body_water),
                bone_mass_kg=_round(bone_mass, 2),
                basal_metabolic_rate_kcal=_round(bmr, 0),
                visceral_fat_rating=max(1, visceral_fat),
            )
        )

    return series


def _to_nanos(moment: datetime) -> int:
    return int(moment.timestamp() * _NANOS_PER_SECOND)


def _point(data_type: str, moment: datetime, value: float, *, is_int: bool = False) -> dict:
    nanos = str(_to_nanos(moment))
    val = {"intVal": int(value)} if is_int else {"fpVal": float(value)}
    return {
        "startTimeNanos": nanos,
        "endTimeNanos": nanos,
        "dataTypeName": data_type,
        "originDataSourceId": _ORIGIN_DATA_SOURCE,
        "value": [val],
    }


@dataclass
class MockGoogleHealthConnector:
    """Stand-in for the live Google Fit connector, yielding fake BIA data.

    Drop-in for the Path A (API) connector during development: same output shape,
    no network. Construct with the knobs you need and call the ``fetch_*`` methods.
    """

    months: int = 12
    end_date: datetime | None = None
    seed: int = 20260708
    height_m: float = 1.78
    # Credential the live connector would present to the Google Fit API. It is
    # decrypted from the local store at the retrieval trigger (see
    # ``health_sync.sync``); the mock only records it to model that dependency.
    api_key: str | None = None
    _series: list[BiaMeasurement] = field(default_factory=list, init=False, repr=False)

    def _ensure_series(self) -> list[BiaMeasurement]:
        if not self._series:
            self._series = generate_bia_series(
                self.months,
                end_date=self.end_date,
                height_m=self.height_m,
                seed=self.seed,
            )
        return self._series

    def fetch_bia_measurements(self) -> list[BiaMeasurement]:
        """Return the parsed BIA series, oldest first — feed to the openEHR mapper."""
        return list(self._ensure_series())

    def fetch_raw_dataset(self) -> list[dict]:
        """Return the series as raw Google Fit ``datasets.get`` responses.

        One response per Fit data type (weight, body fat, muscle mass, ...), each
        with a nanosecond ``minStartTimeNs``/``maxEndTimeNs`` window and a ``point``
        list — mirroring what ``fetch_raw_dataset`` would get from the live API.
        """
        series = self._ensure_series()
        if not series:
            return []

        streams: list[tuple[str, list[dict]]] = []
        for data_type, extract, is_int in (
            (DATA_TYPE_WEIGHT, lambda m: m.weight_kg, False),
            (DATA_TYPE_BODY_FAT, lambda m: m.body_fat_pct, False),
            (DATA_TYPE_SKELETAL_MUSCLE, lambda m: m.skeletal_muscle_mass_kg, False),
            (DATA_TYPE_BODY_WATER, lambda m: m.body_water_pct, False),
            (DATA_TYPE_BONE_MASS, lambda m: m.bone_mass_kg, False),
            (DATA_TYPE_BMR, lambda m: m.basal_metabolic_rate_kcal, False),
            (DATA_TYPE_VISCERAL_FAT, lambda m: m.visceral_fat_rating, True),
        ):
            points = [_point(data_type, m.measured_at, extract(m), is_int=is_int) for m in series]
            streams.append((data_type, points))

        min_ns = str(_to_nanos(series[0].measured_at))
        max_ns = str(_to_nanos(series[-1].measured_at))
        return [
            {
                "minStartTimeNs": min_ns,
                "maxEndTimeNs": max_ns,
                "dataSourceId": f"derived:{data_type}:com.google.android.gms:merged",
                "point": points,
            }
            for data_type, points in streams
        ]


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    connector = MockGoogleHealthConnector()
    print(f"Fetched {connector.months} months of mock BIA measurements:\n")
    for reading in connector.fetch_bia_measurements():
        print(
            f"  {reading.measured_at:%Y-%m-%d}  "
            f"{reading.weight_kg:5.1f} kg  "
            f"{reading.body_fat_pct:4.1f}% fat  "
            f"{reading.skeletal_muscle_mass_kg:4.1f} kg muscle  "
            f"BMI {reading.bmi:4.1f}"
        )
