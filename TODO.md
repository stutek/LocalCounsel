---
type: Backlog
title: TODO — Gaps, Weaknesses & Future Work
description: Consolidated backlog of known gaps, weaknesses, and risks across the health-sync, openEHR persistence, encryption, anonymization, and AI-advice features.
tags: [todo, backlog, gaps, risks, security, health, openEHR]
timestamp: 2026-07-08T17:40:00+02:00
---

# TODO — Gaps, Weaknesses & Future Work

Consolidated, honest inventory of what is **not** done or **not** fully robust in
the Longevity Mentor health pipeline. Grouped by area; each item notes the risk.
Related design detail lives in
[health-integration-architecture.md](/docs/longevity-coach/health-integration-architecture.md)
(esp. §7) and [bia-e2e-flow.md](/docs/longevity-coach/bia-e2e-flow.md).

Priority key: **P1** = correctness/safety/privacy risk or blocks real use · **P2** =
important robustness/fidelity · **P3** = nice-to-have / polish.

---

## 1. Security & Encryption

- [ ] **(P1) Passphrase strength is the root of trust and is unenforced beyond length.**
  scrypt slows brute force but cannot rescue a weak passphrase. Only a 12-char
  minimum is checked — no strength/entropy estimation, no dictionary check.
- [ ] **(P1) No recovery path — a lost passphrase means permanently lost medical data.**
  By design there is no backdoor. Need a documented, user-controlled recovery
  option (e.g. an offline recovery key / sealed backup) so data loss is a choice,
  not an accident.
- [ ] **(P2) No brute-force throttling / lockout on repeated failed unlocks.**
  scrypt cost is the only speed bump; add attempt rate-limiting or backoff.
- [ ] **(P2) Keys/passphrase cannot be reliably zeroed in Python memory.**
  `bytes`/`str` are immutable and may be copied by the GC; a memory capture could
  expose the DEK/passphrase. Consider `memoryview`/`bytearray` handling or OS
  keyring integration for the derived key.
- [ ] **(P2) Metadata is not encrypted.** Composition UIDs, row-insert timestamps,
  the `meta` table (salt, KDF params, wrapped DEK), and record **count** are stored
  in clear. Content is safe, but a thief learns *how many* records exist and *when*
  rows were written. Document as accepted, or encrypt/pad if the threat model needs it.
- [ ] **(P3) GCM nonces are random 96-bit per record (birthday bound ~2³² writes).**
  Fine at personal scale; revisit (deterministic/counter nonce or per-record subkey)
  if write volume ever grows large.
- [ ] **(P2) File permissions (`0700`/`0600`) are best-effort and POSIX-only.**
  No protection on filesystems/OSes without chmod semantics; document platform caveats.
- [ ] **(P3) scrypt cost parameters are fixed defaults;** add periodic re-tuning /
  re-wrapping as hardware improves (params are already persisted per-DB to allow this).

## 2. openEHR Fidelity

- [ ] **(P1) Compositions are canonical/minimal, NOT OPT-validated.** Values map to
  recognizable archetype/element paths but are never validated against a real
  Operational Template. Malformed or out-of-range data could be stored silently.
  Build the OPT/JSON-schema validation gate (§7).
- [ ] **(P2) No EHRbase / AQL query layer.** Retrieval is decrypt-all-and-filter
  in memory — fine for one user's history, but there is no true AQL. `all_compositions`
  scans the whole store.
- [ ] **(P2) Archetype choices for the BIA cluster are provisional** (e.g. the
  `body_composition.v0#…` element paths are illustrative). Confirm against published
  archetypes / an OPT before treating them as canonical.

## 3. Ingestion / Connectors

- [ ] **(P1) Only the MOCK Google Health connector exists.** Path A (live OAuth
  loopback + `fitness/v1` REST) and Path B (Google Takeout ZIP parser) from the
  architecture are unbuilt. There is no parser from the raw Fit `datasets.get`
  payload back into measurements.
- [ ] **(P2) The mock uses invented `com.google.body.*` data types.** Only
  `com.google.weight` and `com.google.body.fat.percentage` are real Fit types; the
  richer BIA fields are modeled as vendor streams. A live connector/mapper will need
  rework against real vendor namespaces (e.g. `com.withings.*`).
- [ ] **(P3) Mock nits:** `_ORIGIN_DATA_SOURCE` hardcodes `raw:com.google.weight:…`
  for all point types; the BMR formula comment says "Mifflin-St Jeor-ish" but the
  expression is Katch-McArdle-shaped; monthly steps are 30-day, not calendar months.

## 4. External AI / Hybrid Cloud

- [ ] **(P1) "External AI" currently hits the LOCAL llama-server.** `ask_nutrition_advice`
  defaults to `assistant.ask` → `127.0.0.1:8080` (Gemma). The paid frontier-model
  path (Claude/Gemini) behind the Dify Anonymizer→PromptTool chain, plus the
  air-gapped toggle, are unbuilt. Docstrings say "external frontier model" — either
  build the real cloud client (with explicit opt-in) or keep the naming honest.
- [ ] **(P2) Anonymization is by construction, not a general filter.**
  `build_nutrition_prompt` only emits relative offsets + numbers, so nothing leaks —
  but the architecture's general-purpose PII scrubber (name/ID scrubbing, age
  fuzzing ±15%) does not exist and this won't generalize to arbitrary AQL results.
- [x] **(P3) The prompt omits age/sex entirely** — **done.** `build_nutrition_prompt`
  now accepts a `SubjectProfile`; it includes sex and a ±15% **fuzzed age band**
  (exact age never emitted), per the anonymization spec (§6.3). The profile is
  stored encrypted under the same key in the E2E flow.

## 5. LLM-Assisted Mapping (Gemma) — see §7 of the architecture doc

- [ ] **(P2)** Add a body-composition (BIA) row to the §4 mapping table — **done** in
  the doc; keep it in sync as archetypes are confirmed.
- [ ] **(P2)** Define the confidence-verdict schema and the Gemma mapping prompt.
- [ ] **(P1)** Implement the deterministic OPT/JSON-schema validation gate (shared
  with item 2.1).
- [ ] **(P2)** Implement the persistent mapping registry keyed by `(vendor, field, unit)`.
- [ ] **(P1)** Implement the human-in-the-loop (HITL) review queue for low-confidence
  / novel mappings.
- [ ] **(P2)** Log every auto-mapping and human decision for auditability.

## 6. Safety, Compliance & Product

- [ ] **(P1) Safety Filtering is not implemented in code.** The requirement to flag
  high-risk recommendations and force human medical oversight exists only as prompt
  framing text, not an enforced check on model output.
- [ ] **(P2) Blood-panel / biomarker PDF ingestion** (a stated functional requirement)
  is unbuilt.
- [ ] **(P3) Dify orchestration layer** (workflow, RAG KB, scheduler, anonymizer tool)
  is described in the architecture but not wired to this code.

## 7. Testing

- [ ] **(P2) The end-to-end AI test needs a live model** (`nox -s test`); it is not
  exercised in the fast unit suite. CI without a model only runs the offline path.
- [ ] **(P3) Untested edge cases:** `generate_bia_series(months=0)` / empty-series
  `ValueError` paths; naive-datetime coercion; raw-dataset stream completeness (only
  the weight stream's point count is asserted); single-reading `build_nutrition_prompt`
  degenerate delta/swing.
- [ ] **(P3) Brittle test assertion:** the `\b20\d{2}\b` anonymization regex would
  false-fail on any 4-digit metric beginning "20" (e.g. a BMR of 2040) if such a value
  ever enters the prompt.

---

_Last reviewed: 2026-07-08. Update this file as items land or new gaps surface._
