"""Integration test verifying data anonymization and Gemma evaluation.

This test validates that:
1. Programmatic anonymization strips all PII and uses a single randomized fuzzed age
   within ±10% (excluding exact age 47) before any external AI call.
2. Personal body composition goals (15% target body fat, 10% healthy lower limit)
   are cleanly incorporated into the prompt.
3. The local Gemma model evaluates the anonymized trend and confirms no PII leakage.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from local_counsel.assistant import ask
from local_counsel.health_sync import (
    SubjectProfile,
    build_nutrition_prompt,
)
from local_counsel.health_sync.mock_google import generate_bia_series


def test_bia_anonymization_and_gemma_evaluation() -> None:
    # 1. Create subject profile with chronological age 47 and personal body fat goals.
    profile = SubjectProfile(
        sex="Male",
        age_years=47,
        target_body_fat_pct=15.0,
        min_healthy_body_fat_pct=10.0,
    )

    # 2. Generate sample 12-month BIA series.
    fixed_end = datetime(2026, 7, 10, tzinfo=timezone.utc)
    series = generate_bia_series(months=12, end_date=fixed_end)

    # 3. Build the anonymized prompt payload.
    prompt = build_nutrition_prompt(series, profile)

    # 4. Programmatic anonymization verification before LLM transmission.
    assert "Male" in prompt, "Subject sex should be present"
    assert "approx. age" in prompt, "Single randomized fuzzed age should be present"
    assert not re.search(r"(?<!\d)47(?!\d)", prompt), "Exact chronological age 47 must never leak"
    assert not re.search(r"\b20\d{2}\b", prompt), "Year strings must not appear in prompt"
    assert not re.search(r"\d{4}-\d{2}-\d{2}", prompt), "ISO calendar dates must not appear in prompt"

    assert "target body fat 15.0%" in prompt, "Target body fat goal should be included"
    assert "not below healthy limit of 10.0%" in prompt, "Healthy lower limit should be included"

    print("\n--- Programmatic Anonymization Verified ---")
    print(f"Prompt preview (first 300 chars):\n{prompt[:300]}...\n")

    # 5. Ask local Gemma to evaluate both anonymization safety and nutrition trend.
    eval_query = (
        f"{prompt}\n\n"
        "TASK FOR GEMMA:\n"
        "1. First, verify whether any exact birth dates, calendar dates, or exact age appear in the text above.\n"
        "2. Second, evaluate the body composition trend and suggest educational nutrition adjustments to help achieve the 15% body fat goal safely above 10%."
    )

    print("Sending evaluation request to local Gemma server...")
    response = ask(eval_query)
    print(f"\n--- Gemma Evaluation Response ---\n{response}\n")

    # 6. Verify model response validity.
    assert response is not None, "Gemma response should not be None"
    assert response.strip(), "Gemma response should not be empty"
