"""End-to-end: mock Google Health BIA -> encrypted openEHR -> external AI advice.

Exercises the full retrieval-to-reasoning path the Longevity Mentor uses, now
routed through the encrypted local medical repository:

  1. RETRIEVE 12 months of BIA measurements from the mock Google Health connector.
  2. MAP each reading to an openEHR composition (deterministic UUIDv5).
  3. STORE the compositions in the per-user, passphrase-encrypted SQLite repo
     (AES-256-GCM). Reopen it and READ the data back — the store is the source
     of truth, so the advice is derived from decrypted, persisted records.
  4. SUMMARIZE weight/body-fat/hydration/muscle fluctuations into an anonymized
     prompt (no PII, no calendar dates).
  5. ASK the external AI for educational nutrition guidance and assert it answers.

Like ``test_llm_integration.py`` this is an INTEGRATION test: it needs a running
model server, which the nox ``test`` session boots first (``nox -s test``).

A BPMN-style diagram of this flow lives in ``docs/bia-e2e-flow.md``.
"""

from __future__ import annotations

import json
import re

from local_counsel.health_sync import (
    GOOGLE_HEALTH_API_KEY,
    SubjectProfile,
    ask_nutrition_advice,
    build_nutrition_prompt,
    trigger_bia_sync,
)
from local_counsel.openehr import EncryptedOpenEhrStore, composition_to_measurement

PASSPHRASE = "e2e-correct-horse-battery-staple"
PROFILE_KEY = "subject_profile"


def test_bia_to_encrypted_openehr_to_nutrition_advice(tmp_path) -> None:
    # 0. PROVISION the Google Health credential and the subject profile (PII),
    #    both encrypted under the same key.
    with EncryptedOpenEhrStore.open("e2e-user", PASSPHRASE, base_dir=tmp_path) as store:
        store.put_secret(GOOGLE_HEALTH_API_KEY, "fake-oauth-token-xyz")
        store.put_secret(PROFILE_KEY, json.dumps(SubjectProfile("Male", 42).as_dict()))

    # 1.-3. TRIGGER the sync: the passphrase gateway unlocks the store, the API
    # key is decrypted, then BIA data is retrieved, mapped, and stored encrypted.
    with trigger_bia_sync("e2e-user", PASSPHRASE, base_dir=str(tmp_path), months=12) as store:
        assert store.count() == 12
        db_path = store.path

    # Nothing sensitive is readable in the raw file without the passphrase —
    # neither clinical values nor the API key.
    raw = db_path.read_bytes()
    assert b"body_weight" not in raw and b"magnitude" not in raw
    assert b"fake-oauth-token-xyz" not in raw

    # Reopen and READ BACK — the persisted store drives the analysis.
    with EncryptedOpenEhrStore.open("e2e-user", PASSPHRASE, base_dir=tmp_path) as store:
        restored = [composition_to_measurement(c) for c in store.all_compositions()]
        profile = SubjectProfile.from_dict(json.loads(store.get_secret(PROFILE_KEY)))
    restored.sort(key=lambda m: m.measured_at)
    assert len(restored) == 12

    # 4. Build the anonymized prompt from the stored data + profile. Sex is
    #    included and the age is fuzzed to a band; no exact age or dates may leak.
    prompt = build_nutrition_prompt(restored, profile)
    assert "Male" in prompt and "age band" in prompt
    assert not re.search(r"(?<!\d)42(?!\d)", prompt)  # exact age never emitted
    assert not re.search(r"\d{4}-\d{2}-\d{2}", prompt)
    print("Anonymized nutrition prompt (from encrypted store):\n" + prompt)

    # 5. ASK the external AI for nutrition advice on the fluctuations.
    advice = ask_nutrition_advice(restored, profile)
    print("\nModel nutrition advice:\n" + advice)

    assert advice is not None, "Advice should not be null"
    assert advice.strip(), "Advice should not be empty"
