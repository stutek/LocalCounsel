"""End-to-end browser demo/validation: real pipeline -> local Gemma advice.

Runs headless + fast in the pipeline (``nox -s e2e``, last validation stage) and
headed + slowed with on-screen narration as a live demo (``nox -s demo``). Same
test, different flags.

Data source is an explicit parameter (see conftest): synthetic mock data by
default (safe to commit), or ``--takeout-zip PATH`` for a real Google Health
export.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page

from _demo import DEMO_PAGE, ask_via_dify, make_narrator, served_model

pytestmark = pytest.mark.dify  # runs through the Dify orchestration stack
from local_counsel.health_sync import (
    MockGoogleHealthConnector,
    SubjectProfile,
    build_nutrition_prompt,
    parse_takeout_zip,
)
from local_counsel.openehr import (
    EncryptedOpenEhrStore,
    bia_to_composition,
    composition_to_measurement,
)

PASSPHRASE = "demo-longevity-passphrase-2026"


def _load_series(config):
    zip_path = config.getoption("--takeout-zip")
    if zip_path:
        return parse_takeout_zip(zip_path, height_m=1.78, source_contains="HealthManager Pro")
    return MockGoogleHealthConnector(months=12).fetch_bia_measurements()


def test_nutrition_advice_demo(page: Page, request, tmp_path) -> None:
    series = _load_series(request.config)
    assert series, "no BIA readings to demo"

    page.goto(DEMO_PAGE.as_uri())
    if request.config.getoption("--pause"):
        page.pause()  # Playwright Inspector: step through the rest by hand
    nar = make_narrator(page, request)  # Play/Pause + Next controls on the overlay

    # 1 — INGEST
    page.evaluate("n => window.demo.stage(n)", 1)
    nar("Step 1 · Ingest",
            f"Parsing {len(series)} monthly body-composition readings from the health export…")
    rows = "".join(
        f"<tr><td>{m.measured_at.date()}</td><td>{m.weight_kg}</td>"
        f"<td>{'-' if m.body_fat_pct is None else m.body_fat_pct}</td></tr>"
        for m in series
    )
    page.evaluate("html => window.demo.set('readings', html)",
                  f"<table><tr><th>month</th><th>weight kg</th><th>body fat %</th></tr>{rows}</table>")

    # 2 — ENCRYPT + STORE (openEHR)
    page.evaluate("n => window.demo.stage(n)", 2)
    nar("Step 2 · Encrypt openEHR",
            "Mapping to openEHR compositions and storing them AES-256-GCM encrypted (idempotent).")
    with EncryptedOpenEhrStore.open("demo-user", PASSPHRASE, base_dir=str(tmp_path)) as store:
        for m in series:
            store.put_composition(bia_to_composition(m))
        store.put_composition(bia_to_composition(series[-1]))  # re-put proves idempotency
        count = store.count()
        db_path = store.path
        restored = sorted(
            (composition_to_measurement(c) for c in store.all_compositions()),
            key=lambda m: m.measured_at,
        )
    leaked = b"body_weight" in db_path.read_bytes()
    assert not leaked, "plaintext leaked into the encrypted store"
    page.evaluate("html => window.demo.set('storage', html)",
                  f"{count} compositions encrypted at rest.<br>"
                  f"<span class='muted'>No plaintext in the DB file: {'✅' if not leaked else '❌'}</span>")

    # 3 — ANONYMIZE
    page.evaluate("n => window.demo.stage(n)", 3)
    profile = SubjectProfile(sex="Male", age_years=47, target_body_fat_pct=15.0, min_healthy_body_fat_pct=10.0)
    prompt = build_nutrition_prompt(restored, profile)
    assert not re.search(r"\d{4}-\d{2}-\d{2}", prompt), "calendar date leaked into the prompt"
    nar("Step 3 · Anonymize",
            "Relative dates, fuzzed age ±10%, no PII — this is all that could ever leave the machine.")
    page.evaluate("t => window.demo.set('prompt', t.replace(/</g,'&lt;'))", prompt)

    # 4 — ASK the local model
    page.evaluate("n => window.demo.stage(n)", 4)
    model = served_model()
    page.evaluate("html => window.demo.set('model', html)", f"Local model: <b>{model}</b>")
    nar("Step 4 · Ask Gemma (via Dify)",
            f"Sending the anonymized prompt through the local Dify app → {model}. No cloud.", seconds=2.0)
    advice = ask_via_dify(prompt).strip()
    assert advice, "Dify/model returned empty advice"

    # 5 — ADVICE
    page.evaluate("n => window.demo.stage(n)", 5)
    html = advice.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
    page.evaluate("h => window.demo.set('advice', h)", html)
    nar("Step 5 · Advice",
            "Educational nutrition guidance from on-device Gemma, with a consult-a-professional disclaimer.",
            seconds=3.0)
    nar.hold_open()  # demo: keep the window up until the presenter closes it
