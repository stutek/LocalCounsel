"""Unit and integration test for the Dify Custom Tool REST server MVP."""

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
    generate_bia_series,
    generate_dify_bia_payload,
)


def test_generate_dify_bia_payload_anonymization_and_goals() -> None:
    profile = SubjectProfile(
        sex="Male",
        age_years=47,
        target_body_fat_pct=15.0,
        min_healthy_body_fat_pct=10.0,
    )
    series = generate_bia_series(months=12)

    # 1. Monthly relative format
    monthly_payload = generate_dify_bia_payload(series, profile, daily=False)
    assert monthly_payload["format"] == "monthly_relative"
    assert monthly_payload["reading_count"] == 12
    assert "Male" in monthly_payload["subject_line"]
    assert "approx. age" in monthly_payload["subject_line"]
    assert not re.search(r"(?<!\d)47(?!\d)", monthly_payload["anonymized_prompt"])
    assert "target body fat 15.0%" in monthly_payload["subject_line"]

    # 2. Daily compact stream format
    daily_payload = generate_dify_bia_payload(series, profile, daily=True)
    assert daily_payload["format"] == "daily_compact"
    assert "day,w_kg,bf_%,hyd_%,mus_kg" in daily_payload["anonymized_prompt"]
    assert not re.search(r"\d{4}-\d{2}-\d{2}", daily_payload["anonymized_prompt"])


def test_dify_bia_http_server_endpoint() -> None:
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
        # Test GET /v1/bia/summary?daily=true
        with urlopen(f"http://127.0.0.1:{port}/v1/bia/summary?daily=true") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))

        assert data["format"] == "daily_compact"
        assert data["reading_count"] == 6
        assert "approx. age" in data["subject_line"]
        assert "target body fat 15.0%" in data["subject_line"]
        assert not re.search(r"(?<!\d)47(?!\d)", data["anonymized_prompt"])
    finally:
        server.shutdown()
        server.server_close()
