"""User/patient-specific goals — the first non-diagnostic OKF record type.

A goal is not a measurement. A BIA reading is a *fact* you observed; a goal is an
*intention*: a metric you want to move, a target value, and a date. This module
models one goal and maps it to a FHIR ``Goal`` resource. (openEHR ``EVALUATION``
mapping + progress linkage come in the next step.)

Learning notes are inline — the FHIR field names are what an interviewer probes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"


@dataclass(frozen=True)
class Goal:
    """One personal goal. Kept vendor-neutral; mapped to FHIR / openEHR on demand."""

    subject_id: str          # whose goal — becomes Patient/<id>
    description: str         # human text, e.g. "Reduce body fat"
    measure_loinc: str       # WHICH metric moves, e.g. 41982-0 = body fat %
    measure_text: str        # display name for that metric
    target_value: float      # the number you're aiming at
    target_unit: str         # UCUM unit, e.g. "%", "kg"
    due_date: date           # by when
    baseline_value: float | None = None   # where you started (for progress %)
    status: str = "active"   # FHIR lifecycleStatus: proposed | active | completed …


def goal_to_fhir(goal: Goal) -> dict:
    """Map a Goal to a FHIR ``Goal`` resource (R4/R5).

    The anatomy an interviewer will ask about:
      * ``description``      — CodeableConcept: WHAT the goal is (free text here).
      * ``subject``          — a Reference to the Patient the goal belongs to.
      * ``target.measure``   — a CodeableConcept (LOINC) naming the metric to move.
      * ``target.detailQuantity`` — the TARGET value + UCUM unit (not a measurement).
      * ``target.dueDate``   — the deadline.
      * ``lifecycleStatus``  — where the goal is in its life (active/completed…).
    Progress is NOT stored here: separate Observations reference this Goal.
    """
    return {
        "resourceType": "Goal",
        "lifecycleStatus": goal.status,
        "description": {"text": goal.description},
        "subject": {"reference": f"Patient/{goal.subject_id}"},
        "target": [
            {
                "measure": {
                    "coding": [
                        {"system": LOINC, "code": goal.measure_loinc, "display": goal.measure_text}
                    ]
                },
                "detailQuantity": {
                    "value": goal.target_value,
                    "unit": goal.target_unit,
                    "system": UCUM,
                    "code": goal.target_unit,
                },
                "dueDate": goal.due_date.isoformat(),
            }
        ],
    }


if __name__ == "__main__":
    import json

    goal = Goal(
        subject_id="simon",
        description="Reduce body fat percentage",
        measure_loinc="41982-0",
        measure_text="Percentage of body fat",
        target_value=18.0,
        target_unit="%",
        due_date=date(2026, 12, 31),
        baseline_value=24.0,
    )
    print(json.dumps(goal_to_fhir(goal), indent=2))
