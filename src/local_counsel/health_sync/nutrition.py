"""Turn a BIA series into an anonymized nutrition-advice question for the AI.

This is the bridge between the mock/live Google Health connector and the external
frontier model. It summarizes 12 months of body-composition *fluctuations*
(weight, body fat, hydration, skeletal muscle) and renders a prompt that carries
**no PII and no absolute dates** — timestamps become relative month offsets
("current", "-1 mo", ...) and, when a subject profile is supplied, the exact age
becomes a ±10% fuzzed band, per the anonymization filter in
``docs/longevity-coach/health-integration-architecture.md`` §6.3.

The pure functions here (:func:`summarize_fluctuations`, :func:`build_nutrition_prompt`)
are LLM-free and unit-testable; :func:`ask_nutrition_advice` wires the prompt to
whatever model ``local_counsel.assistant.ask`` is pointed at.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .mock_google import BiaMeasurement

# Fraction of age used as the ±fuzz half-width, per the anonymization filter
# (docs/longevity-coach/health-integration-architecture.md §6.3): exact age is never emitted, only
# a fuzzed band, to resist database cross-matching re-identification.
AGE_FUZZ_FRACTION = 0.10

# Educational framing + human-oversight nudge, per the Safety Filtering requirement.
_SYSTEM_FRAMING = (
    "You are a longevity-focused nutrition educator. Based on the anonymized "
    "12-month body-composition trend below, give general, educational nutrition "
    "guidance addressing the weight, body-fat, hydration, and muscle changes. "
    "Do not diagnose. Explicitly recommend consulting a qualified professional "
    "before acting on any suggestion."
)


@dataclass(frozen=True)
class SubjectProfile:
    """Minimal demographic context for tailoring nutrition advice.

    Sex is passed through as-is (coarse, non-identifying at population scale); age
    is **never** emitted exactly — :meth:`fuzzed_age_band` turns it into a ±10%
    band, per the anonymization filter (§6.3).
    """

    sex: str
    age_years: int
    target_body_fat_pct: float | None = None
    min_healthy_body_fat_pct: float | None = None

    def fuzzed_age_band(
        self, *, fraction: float = AGE_FUZZ_FRACTION, rng: random.Random | None = None
    ) -> tuple[int, int]:
        """Return an inclusive ``(low, high)`` age band around the exact age.

        The half-width is ``round(age * fraction)`` (at least 1 year). When an
        ``rng`` is supplied the band centre is randomly shifted within ±half-width
        so repeated queries do not reveal a stable centre (anti cross-matching);
        without one the band is deterministic (``age ± half``) for reproducibility.
        The exact age is never one of the returned edges.
        """
        if self.age_years < 0:
            raise ValueError("age_years must be non-negative")
        half = max(1, round(self.age_years * fraction))
        centre = self.age_years
        if rng is not None:
            centre += rng.randint(-half, half)
        return max(0, centre - half), centre + half

    def fuzzed_age(
        self, *, fraction: float = AGE_FUZZ_FRACTION, rng: random.Random | None = None
    ) -> int:
        """Return a single randomized fuzzed age within ±fraction around exact age.

        Prevents midpoint inference and ensures exact age is never returned.
        """
        if self.age_years < 0:
            raise ValueError("age_years must be non-negative")
        half = max(1, round(self.age_years * fraction))
        r = rng or random.Random()
        candidates = [
            a
            for a in range(max(1, self.age_years - half), self.age_years + half + 1)
            if a != self.age_years
        ]
        if not candidates:
            return self.age_years + 1
        return r.choice(candidates)

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"sex": self.sex, "age_years": self.age_years}
        if self.target_body_fat_pct is not None:
            data["target_body_fat_pct"] = self.target_body_fat_pct
        if self.min_healthy_body_fat_pct is not None:
            data["min_healthy_body_fat_pct"] = self.min_healthy_body_fat_pct
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubjectProfile":
        target = float(data["target_body_fat_pct"]) if data.get("target_body_fat_pct") is not None else None
        min_bf = float(data["min_healthy_body_fat_pct"]) if data.get("min_healthy_body_fat_pct") is not None else None
        return cls(
            sex=str(data["sex"]),
            age_years=int(data["age_years"]),
            target_body_fat_pct=target,
            min_healthy_body_fat_pct=min_bf,
        )


@dataclass(frozen=True)
class MetricFluctuation:
    """Start/end/extent summary for one body-composition metric over the window."""

    label: str
    unit: str
    start: float
    end: float
    minimum: float
    maximum: float

    @property
    def delta(self) -> float:
        return round(self.end - self.start, 2)

    @property
    def swing(self) -> float:
        """Peak-to-trough range — the fluctuation magnitude."""
        return round(self.maximum - self.minimum, 2)

    @property
    def direction(self) -> str:
        if self.delta > 0:
            return "up"
        if self.delta < 0:
            return "down"
        return "flat"


@dataclass(frozen=True)
class FluctuationSummary:
    """Aggregate view of the series: per-metric fluctuations + reading count.

    Metrics absent from the source data (e.g. hydration/muscle in a real Beurer
    export that only has weight + body fat) are ``None`` and skipped everywhere.
    """

    months: int
    weight: MetricFluctuation | None
    body_fat: MetricFluctuation | None
    hydration: MetricFluctuation | None
    muscle: MetricFluctuation | None

    def metrics(self) -> list[MetricFluctuation]:
        return [m for m in (self.weight, self.body_fat, self.hydration, self.muscle) if m]


def _metric(
    label: str,
    unit: str,
    values: Sequence[float | None],
) -> MetricFluctuation | None:
    """Summarize a metric, using only the readings that carry it (``None`` if none)."""
    present = [v for v in values if v is not None]
    if not present:
        return None
    return MetricFluctuation(
        label=label,
        unit=unit,
        start=round(present[0], 2),
        end=round(present[-1], 2),
        minimum=round(min(present), 2),
        maximum=round(max(present), 2),
    )


def summarize_fluctuations(series: Sequence[BiaMeasurement]) -> FluctuationSummary:
    """Reduce an oldest-first BIA series to per-metric fluctuation summaries."""
    if not series:
        raise ValueError("series must contain at least one measurement")

    return FluctuationSummary(
        months=len(series),
        weight=_metric("Weight", "kg", [m.weight_kg for m in series]),
        body_fat=_metric("Body fat", "%", [m.body_fat_pct for m in series]),
        hydration=_metric("Hydration (body water)", "%", [m.body_water_pct for m in series]),
        muscle=_metric("Skeletal muscle", "kg", [m.skeletal_muscle_mass_kg for m in series]),
    )


def _relative_label(index: int, total: int) -> str:
    """Month offset from the latest reading: 'current', '-1 mo', ..."""
    offset = (total - 1) - index
    return "current" if offset == 0 else f"-{offset} mo"


def _subject_line(profile: SubjectProfile, rng: random.Random | None) -> str:
    approx_age = profile.fuzzed_age(rng=rng)
    base = f"Subject: {profile.sex}, approx. age {approx_age} (exact age fuzzed ±10% for privacy)."
    if profile.target_body_fat_pct is not None:
        goal_msg = f" Goal: target body fat {profile.target_body_fat_pct}%"
        if profile.min_healthy_body_fat_pct is not None:
            goal_msg += f" (not below healthy limit of {profile.min_healthy_body_fat_pct}%)"
        goal_msg += "."
        base += goal_msg
    return base


def build_nutrition_prompt(
    series: Sequence[BiaMeasurement],
    profile: SubjectProfile | None = None,
    *,
    rng: random.Random | None = None,
) -> str:
    """Render the anonymized nutrition-advice prompt for the external AI.

    Contains only relative month offsets and biometric numbers — no names, IDs,
    or calendar dates ever reach the model. When a :class:`SubjectProfile` is
    given, the subject's **sex** and a **fuzzed age band** are included (never the
    exact age) so advice can be tailored without enabling re-identification.
    """
    summary = summarize_fluctuations(series)

    trend_lines = [
        f"- {m.label} ({m.unit}): {m.start} -> {m.end} "
        f"(net {m.delta:+}, swing {m.swing}, trend {m.direction})"
        for m in summary.metrics()
    ]

    # Compact per-reading table using relative offsets only (no dates). Columns
    # adapt to which metrics the data actually carries (sparse real exports have
    # only weight + body fat).
    columns: list[tuple[str, str]] = []
    if summary.weight:
        columns.append(("weight_kg", "weight_kg"))
    if summary.body_fat:
        columns.append(("body_fat_%", "body_fat_pct"))
    if summary.hydration:
        columns.append(("hydration_%", "body_water_pct"))
    if summary.muscle:
        columns.append(("muscle_kg", "skeletal_muscle_mass_kg"))

    table_header = "month | " + " | ".join(h for h, _ in columns)
    table_rows = [
        f"{_relative_label(i, summary.months)} | "
        + " | ".join(
            (lambda v: "-" if v is None else str(v))(getattr(m, attr)) for _, attr in columns
        )
        for i, m in enumerate(series)
    ]

    subject = f"{_subject_line(profile, rng)}\n" if profile is not None else ""

    return (
        f"{_SYSTEM_FRAMING}\n\n"
        f"{subject}"
        f"Window: {summary.months} monthly readings (oldest first).\n\n"
        "Net fluctuations:\n"
        + "\n".join(trend_lines)
        + "\n\nPer-reading trend:\n"
        + table_header
        + "\n"
        + "\n".join(table_rows)
        + "\n\nQuestion: What educational nutrition adjustments do these "
        "weight, body-fat, hydration, and muscle fluctuations suggest?"
    )


def ask_nutrition_advice(
    series: Sequence[BiaMeasurement],
    profile: SubjectProfile | None = None,
    ask: Callable[[str], str] | None = None,
) -> str:
    """Build the anonymized prompt and ask the external AI for nutrition advice.

    ``ask`` defaults to :func:`local_counsel.assistant.ask` (the pluggable model
    endpoint); inject a callable to test the wiring without a live model.
    """
    if ask is None:
        from ..assistant import ask as ask  # noqa: PLC0414 - lazy import, avoid cycle

    prompt = build_nutrition_prompt(series, profile)
    return ask(prompt)


def build_daily_nutrition_prompt(
    series: Sequence[BiaMeasurement],
    profile: SubjectProfile | None = None,
    *,
    rng: random.Random | None = None,
) -> str:
    """Render an ultra-compact daily BIA prompt without monthly aggregation.

    Converts calendar dates to relative day offsets (d0 = latest reading) and
    formats rows compactly to fit hundreds of daily readings within token budgets.
    """
    if not series:
        raise ValueError("series must not be empty")

    sorted_series = sorted(series, key=lambda m: m.measured_at)
    latest_dt = sorted_series[-1].measured_at

    rows = []
    for m in sorted_series:
        day_offset = (m.measured_at.date() - latest_dt.date()).days
        day_label = f"d{day_offset}"
        rows.append(
            f"{day_label},{m.weight_kg},{m.body_fat_pct},{m.body_water_pct},{m.skeletal_muscle_mass_kg}"
        )

    first, last = sorted_series[0], sorted_series[-1]
    net_w = round(last.weight_kg - first.weight_kg, 2)
    net_bf = round(last.body_fat_pct - first.body_fat_pct, 2)

    subject = f"{_subject_line(profile, rng)}\n" if profile is not None else ""

    return (
        f"{_SYSTEM_FRAMING}\n\n"
        f"{subject}"
        f"Window: {len(sorted_series)} daily readings (compact format: day_offset,weight_kg,body_fat_pct,hydration_pct,muscle_kg).\n"
        f"Net change: weight {net_w:+} kg, body fat {net_bf:+} %.\n\n"
        "Daily readings (oldest first):\n"
        "day,w_kg,bf_%,hyd_%,mus_kg\n"
        + "\n".join(rows)
        + "\n\nQuestion: What educational nutrition adjustments do these daily "
        "weight, body-fat, hydration, and muscle fluctuations suggest?"
    )
