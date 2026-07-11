"""Deterministic parser for a real Google Health / Fitbit Takeout export.

Verified against an actual export: BIA body-composition data arrives as **CSV**
(not the Google Fit ``datasets.get`` JSON the mock emits), under
``Takeout/Google Health/Physical Activity_GoogleData/``:

* ``weight.csv``            — ``timestamp, weight grams, data source`` (weight in grams)
* ``body_fat_YYYY-MM-01.csv`` — ``timestamp, body fat percentage, data source`` (monthly)

Beurer scale data is identified only by the ``data source`` column value
``HealthManager Pro Health Connect`` (its HealthManager Pro app bridging via
Android Health Connect); there is no literal "Beurer" token and it is absent from
the Fitbit ``Paired Devices`` list. Use ``source_contains`` to filter provenance.

Extraction is deterministic and LLM-free. Raw per-reading rows are aggregated to
one :class:`BiaMeasurement` per calendar month (median), keeping the series small
and idempotent for openEHR upsert. Only weight, body fat %, and (optionally,
derived) BMI are populated — the richer BIA fields are ``None`` (absent in the
export).
"""

from __future__ import annotations

import csv
import io
import statistics
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .mock_google import BiaMeasurement

_WEIGHT_CSV_SUFFIX = "Physical Activity_GoogleData/weight.csv"
_BODY_FAT_PREFIX = "Physical Activity_GoogleData/body_fat_"


def _parse_ts(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp like ``2025-06-19T21:59:19.11Z`` (UTC)."""
    dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _rows(zf: zipfile.ZipFile, name: str) -> list[list[str]]:
    with zf.open(name) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8")
        reader = csv.reader(text)
        return [r for r in reader if r]


def _collect(
    zf: zipfile.ZipFile,
    predicate,
    value_col: int,
    convert,
    source_contains: str | None,
) -> dict[tuple[int, int], list[tuple[datetime, float]]]:
    """Group ``(timestamp, value)`` by (year, month) across matching CSV members."""
    by_month: dict[tuple[int, int], list[tuple[datetime, float]]] = defaultdict(list)
    for name in zf.namelist():
        if not predicate(name):
            continue
        rows = _rows(zf, name)
        if not rows:
            continue
        for row in rows[1:]:  # skip header
            if len(row) <= value_col:
                continue
            source = row[2] if len(row) > 2 else ""
            if source_contains and source_contains.lower() not in source.lower():
                continue
            try:
                ts = _parse_ts(row[0])
                val = convert(row[value_col])
            except (ValueError, IndexError):
                continue
            by_month[(ts.year, ts.month)].append((ts, val))
    return by_month


def parse_takeout_zip(
    source: str | Path | bytes,
    *,
    height_m: float | None = None,
    source_contains: str | None = None,
) -> list[BiaMeasurement]:
    """Parse a Google Health Takeout ZIP into a monthly BIA series (oldest first).

    ``height_m`` — if given, BMI is derived per month from the median weight.
    ``source_contains`` — keep only rows whose ``data source`` contains this
    substring (e.g. ``"HealthManager Pro"`` for Beurer-only).
    """
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        weight_by_month = _collect(
            zf, lambda n: n.endswith(_WEIGHT_CSV_SUFFIX), 1, lambda g: int(g) / 1000.0, source_contains
        )
        fat_by_month = _collect(
            zf, lambda n: _BODY_FAT_PREFIX in n and n.endswith(".csv"), 1, float, source_contains
        )

    months = sorted(set(weight_by_month) | set(fat_by_month))
    series: list[BiaMeasurement] = []
    for ym in months:
        weights = [v for _, v in weight_by_month.get(ym, [])]
        fats = [v for _, v in fat_by_month.get(ym, [])]
        if not weights:
            continue  # weight is the anchor metric
        weight_kg = round(statistics.median(weights), 2)
        body_fat = round(statistics.median(fats), 2) if fats else None
        # Representative timestamp: latest reading in the month.
        stamps = [t for t, _ in weight_by_month.get(ym, [])] + [t for t, _ in fat_by_month.get(ym, [])]
        measured_at = max(stamps)
        bmi = round(weight_kg / (height_m * height_m), 1) if height_m else None
        series.append(
            BiaMeasurement(
                measured_at=measured_at,
                weight_kg=weight_kg,
                body_fat_pct=body_fat,
                bmi=bmi,
            )
        )
    return series
