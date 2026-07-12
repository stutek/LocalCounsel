"""End-to-end demo config. Explicit CLI parameters — no environment variables.

    --takeout-zip PATH   drive the demo from a real Google Health export
                         (default: synthetic mock data, safe to commit/share)
    --pause              drop into the Playwright Inspector for step-by-step debug

Pacing/browser flags come from pytest-playwright: --headed, --slowmo MS, --browser.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the repo's src/ importable so the demo drives the real pipeline.
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


APP_URL_FILE = ROOT / "build" / "dify" / "app_url.txt"


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "dify: end-to-end demo that drives the provisioned Dify stack")


def resolve_dify_url(config) -> str | None:
    """Explicit --dify-url wins; otherwise use the URL the pipeline's setup wrote."""
    url = config.getoption("--dify-url")
    if url:
        return url
    return APP_URL_FILE.read_text(encoding="utf-8").strip() if APP_URL_FILE.exists() else None


def pytest_addoption(parser) -> None:
    group = parser.getgroup("longevity-demo")
    group.addoption(
        "--takeout-zip",
        action="store",
        default=None,
        help="Path to a real Google Health Takeout ZIP (default: synthetic mock data).",
    )
    group.addoption(
        "--pause",
        action="store_true",
        default=False,
        help="Open the Playwright Inspector and pause for step-by-step debugging.",
    )
    group.addoption(
        "--manual",
        action="store_true",
        default=False,
        help="Manual stepping: the narration overlay advances only when 'Next' is clicked "
        "(otherwise it auto-advances on a pauseable countdown). Headed demos only.",
    )
    group.addoption(
        "--start-paused",
        action="store_true",
        default=False,
        help="Start the narration overlay in a paused state with 'Auto Play' and 'Next' buttons.",
    )
    group.addoption(
        "--dify-url",
        action="store",
        default=None,
        help="URL of the Dify Longevity Mentor chat app (e.g. http://localhost/chat/<id>). "
        "The Dify greeting demo skips unless this is given and reachable.",
    )
