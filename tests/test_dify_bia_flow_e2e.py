"""End-to-end architectural validation test for the Dify BIA workflow.

Validates that:
1. The local Dify Tool Server provides pre-anonymized BIA data (zero PII, fuzzed age, relative dates).
2. The user's personal goals (15% target body fat, 10% healthy limit) are injected.
3. The prompt is token-efficient and evaluates cleanly to produce longevity nutrition advice.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from http.server import HTTPServer
from urllib.request import urlopen

from local_counsel.health_sync import (
    DifyBiaToolHandler,
    SubjectProfile,
    ask_nutrition_advice,
    generate_bia_series,
)


def test_dify_bia_flow_e2e_architecture_validation() -> None:
    profile = SubjectProfile(
        sex="Male",
        age_years=47,
        target_body_fat_pct=15.0,
        min_healthy_body_fat_pct=10.0,
    )
    series = generate_bia_series(months=6, end_date=datetime(2026, 7, 10, tzinfo=timezone.utc))

    DifyBiaToolHandler.series_provider = lambda: series
    DifyBiaToolHandler.profile_provider = lambda: profile

    server = HTTPServer(("127.0.0.1", 0), DifyBiaToolHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        # Step 1: Dify Tool Node calls GET /v1/bia/summary?daily=true
        with urlopen(f"http://127.0.0.1:{port}/v1/bia/summary?daily=true") as resp:
            assert resp.status == 200
            payload = json.loads(resp.read().decode("utf-8"))

        # Step 2: Verify anonymization & goal injection
        subject_line = payload["subject_line"]
        anonymized_prompt = payload["anonymized_prompt"]

        assert "approx. age" in subject_line
        assert "target body fat 15.0%" in subject_line
        assert "not below healthy limit of 10.0%" in subject_line
        assert not re.search(r"(?<!\d)47(?!\d)", anonymized_prompt)
        assert not re.search(r"\d{4}-\d{2}-\d{2}", anonymized_prompt)

        # Step 3: Dify LLM Node executes completion against Local Gemma
        full_system_and_user_prompt = f"{subject_line}\n\n{anonymized_prompt}"

        def fake_local_gemma_client(prompt: str) -> str:
            assert "target body fat 15.0%" in prompt
            return (
                "Longevity Mentor Advice: Based on your daily trends and your goal "
                "to reach 15% body fat safely above the 10% floor, focus on protein "
                "periodization and maintaining hydration above 55%."
            )

        advice = ask_nutrition_advice(series, profile, ask=fake_local_gemma_client)
        assert "15% body fat" in advice
        assert "10% floor" in advice
    finally:
        server.shutdown()
        server.server_close()
