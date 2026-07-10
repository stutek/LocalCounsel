"""Health data ingestion for the Longevity Mentor.

The sync engine has two halves (see ``docs/longevity-coach/health-integration-architecture.md``):
a **Connector** that retrieves raw records from Google Health/Fit, and a
**Mapper** that translates them into openEHR compositions. This package currently
ships the connector side; the mock connector below lets the rest of the pipeline
be built and tested without live Google API credentials.
"""

from __future__ import annotations

from .mock_google import (
    BiaMeasurement,
    MockGoogleHealthConnector,
    generate_bia_series,
)
from .nutrition import (
    FluctuationSummary,
    MetricFluctuation,
    SubjectProfile,
    ask_nutrition_advice,
    build_nutrition_prompt,
    summarize_fluctuations,
)
from .sync import GOOGLE_HEALTH_API_KEY, MissingCredentialError, trigger_bia_sync

__all__ = [
    "BiaMeasurement",
    "MockGoogleHealthConnector",
    "generate_bia_series",
    "FluctuationSummary",
    "MetricFluctuation",
    "SubjectProfile",
    "ask_nutrition_advice",
    "build_nutrition_prompt",
    "summarize_fluctuations",
    "trigger_bia_sync",
    "MissingCredentialError",
    "GOOGLE_HEALTH_API_KEY",
]
