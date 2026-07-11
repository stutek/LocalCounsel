"""Dify Custom Tool REST microservice for BIA data extraction & anonymization.

Exposes an endpoint / function Dify workflows can call to retrieve pre-anonymized,
token-efficient BIA body composition streams (daily or monthly) with randomized
age fuzzing and user goals embedded.
"""

from __future__ import annotations

import json
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse

from .mock_google import BiaMeasurement
from .nutrition import (
    SubjectProfile,
    _subject_line,
    build_daily_nutrition_prompt,
    build_nutrition_prompt,
)


def generate_dify_bia_payload(
    series: Sequence[BiaMeasurement],
    profile: SubjectProfile | None = None,
    *,
    daily: bool = False,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Generate a clean, pre-anonymized BIA payload dictionary ready for Dify LLM nodes.

    Never emits exact chronological age or absolute calendar dates.
    """
    if daily:
        prompt = build_daily_nutrition_prompt(series, profile, rng=rng)
        fmt = "daily_compact"
    else:
        prompt = build_nutrition_prompt(series, profile, rng=rng)
        fmt = "monthly_relative"

    subject_str = _subject_line(profile, rng).strip() if profile else ""

    return {
        "anonymized_prompt": prompt,
        "subject_line": subject_str,
        "reading_count": len(series),
        "format": fmt,
    }


class DifyBiaToolHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler serving /v1/bia/summary for local Dify orchestration."""

    series_provider: Any = None
    profile_provider: Any = None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/v1/bia/summary":
            self.send_error(404, "Not Found")
            return

        params = parse_qs(parsed.query)
        daily = params.get("daily", ["false"])[0].lower() in ("true", "1")

        provider_series = getattr(self.__class__, "series_provider", None)
        provider_profile = getattr(self.__class__, "profile_provider", None)

        series = provider_series() if callable(provider_series) else []
        profile = provider_profile() if callable(provider_profile) else None

        payload = generate_dify_bia_payload(series, profile, daily=daily)

        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str = "127.0.0.1", port: int = 8088) -> HTTPServer:
    server = HTTPServer((host, port), DifyBiaToolHandler)
    return server
