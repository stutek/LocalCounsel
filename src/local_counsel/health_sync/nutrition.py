"""Turn a BIA series into an anonymized nutrition-advice question for the AI.

This is the bridge between the mock/live Google Health connector and the external
frontier model. It summarizes 12 months of body-composition *fluctuations*
(weight, body fat, hydration, skeletal muscle) and renders a prompt that carries
**no PII and no absolute dates** — timestamps become relative month offsets
("current", "-1 mo", ...) and, when a subject profile is supplied, the exact age
becomes a ±15% fuzzed band, per the anonymization filter in
``docs/health-integration-architecture.md`` §6.3.

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
# (docs/health-integration-architecture.md §6.3): exact age is never emitted, only
# a fuzzed band, to resist database cross-matching re-identification.
AGE_FUZZ_FRACTION = 0.15

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
    is **never** emitted exactly — :meth:`fuzzed_age_band` turns it into a ±15%
    band, per the anonymization filter (§6.3).
    """

    sex: str
    age_years: int

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

    def as_dict(self) -> dict[str, Any]:
        return {"sex": self.sex, "age_years": self.age_years}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubjectProfile":
        return cls(sex=str(data["sex"]), age_years=int(data["age_years"]))


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
    """Aggregate view of the series: per-metric fluctuations + reading count."""

    months: int
    weight: MetricFluctuation
    body_fat: MetricFluctuation
    hydration: MetricFluctuation
    muscle: MetricFluctuation

    def metrics(self) -> list[MetricFluctuation]:
        return [self.weight, self.body_fat, self.hydration, self.muscle]


def _metric(
    label: str,
    unit: str,
    values: Sequence[float],
) -> MetricFluctuation:
    return MetricFluctuation(
        label=label,
        unit=unit,
        start=round(values[0], 2),
        end=round(values[-1], 2),
        minimum=round(min(values), 2),
        maximum=round(max(values), 2),
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
    low, high = profile.fuzzed_age_band(rng=rng)
    return f"Subject: {profile.sex}, age band ~{low}-{high} (exact age fuzzed ±15% for privacy)."


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

    # Compact per-reading table using relative offsets only (no dates).
    table_header = "month | weight_kg | body_fat_% | hydration_% | muscle_kg"
    table_rows = [
        f"{_relative_label(i, summary.months)} | "
        f"{m.weight_kg} | {m.body_fat_pct} | {m.body_water_pct} | {m.skeletal_muscle_mass_kg}"
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
