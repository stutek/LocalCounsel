"""Real end-to-end demo: Google Health/Beurer export -> encrypted openEHR ->
anonymized prompt -> local LLM nutrition advice.

Runs the whole Longevity Mentor scenario against a real Takeout ZIP, entirely
locally. No secrets or health data are written outside a throwaway temp store.

Usage:
    PYTHONPATH=src python3 scripts/demo_nutrition_advice.py <takeout.zip> [--source "HealthManager Pro"]

The model is called over the local OpenAI-compatible endpoint via stdlib urllib
(no `openai` dependency needed), so it works against whatever GGUF llama-server
is currently serving.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.request
from datetime import timezone

from local_counsel.health_sync import SubjectProfile, build_nutrition_prompt, parse_takeout_zip
from local_counsel.openehr import (
    EncryptedOpenEhrStore,
    bia_to_composition,
    composition_to_measurement,
)

LLM_BASE = "http://127.0.0.1:8080/v1"
PASSPHRASE = "demo-longevity-passphrase-2026"


def _http_json(url: str, payload: dict | None = None, timeout: float = 300.0) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def served_model() -> str:
    try:
        return _http_json(f"{LLM_BASE}/models")["data"][0]["id"]
    except Exception as exc:  # pragma: no cover - demo convenience
        return f"<unavailable: {exc}>"


def ask_llm(prompt: str) -> str:
    body = {"model": "gemma", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
    resp = _http_json(f"{LLM_BASE}/chat/completions", body)
    return resp["choices"][0]["message"]["content"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("zip", help="Path to a Google Health Takeout ZIP")
    ap.add_argument("--source", default=None, help="Filter by data source (e.g. 'HealthManager Pro' for Beurer)")
    ap.add_argument("--height", type=float, default=1.78, help="Height in metres for BMI")
    args = ap.parse_args()

    print("=" * 72)
    print("LONGEVITY MENTOR — real BIA nutrition-advice demo")
    print("=" * 72)

    # 1. INGEST — deterministic parse of the real export.
    series = parse_takeout_zip(args.zip, height_m=args.height, source_contains=args.source)
    if not series:
        print("No BIA readings found in export.")
        return 1
    print(f"\n[1] Parsed {len(series)} monthly BIA readings "
          f"({series[0].measured_at.date()} -> {series[-1].measured_at.date()})"
          + (f", source~='{args.source}'" if args.source else ""))

    # 2. STORE — encrypted, per-user openEHR; idempotent upsert.
    with tempfile.TemporaryDirectory() as tmp:
        with EncryptedOpenEhrStore.open("demo-user", PASSPHRASE, base_dir=tmp) as store:
            for m in series:
                store.put_composition(bia_to_composition(m))
            store.put_composition(bia_to_composition(series[-1]))  # re-put: proves idempotency
            print(f"[2] Stored encrypted at {store.path.name}; compositions={store.count()} (idempotent)")
            restored = sorted(
                (composition_to_measurement(c) for c in store.all_compositions()),
                key=lambda m: m.measured_at,
            )

    # 3. ANONYMIZE + PROMPT — from the decrypted store data.
    profile = SubjectProfile(sex="Male", age_years=47, target_body_fat_pct=15.0, min_healthy_body_fat_pct=10.0)
    prompt = build_nutrition_prompt(restored, profile)
    print("\n[3] Anonymized prompt sent to the model (no dates, no exact age, no PII):")
    print("-" * 72)
    print(prompt)
    print("-" * 72)

    # 4. ASK — local model.
    print(f"\n[4] Asking local model: {served_model()}")
    print("=" * 72)
    print(ask_llm(prompt).strip())
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
