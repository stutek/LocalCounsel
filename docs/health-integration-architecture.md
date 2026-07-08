---
type: Architecture
title: Architecture — Google Health to openEHR Sync
description: System design for local Google Health/Fit data ingestion, openEHR mapping, and secure local storage.
tags: [architecture, design, health, openEHR, privacy]
timestamp: 2026-07-08T17:45:00+02:00
---

# Architecture — Google Health to openEHR Sync

This document proposes the local-first system architecture for synchronizing Google Health/Fit records into a local openEHR (Open Electronic Health Record) database to support the privacy-preserving **Longevity Mentor** assistant.

---

## 1. Architectural Philosophy
1. **Strict Local Processing (Privacy first)**: No raw health data or API keys leave the user's local machine. The LLM and the database run completely sandboxed.
2. **Standard-Based Medical Storage**: Avoid vendor lock-in by using **openEHR** (ISO 13606 compliant) archetypes and templates, making the medical record future-proof.
3. **Decoupled Sync and LLM Layers**: The ingestion pipeline operates independently from the compliance checker and RAG engine, ensuring stable performance and ease of testing.

---

## 2. Component Overview

The following diagram illustrates how Google Health data flows into the local openEHR repository and is served to the LocalCounsel assistant:

```mermaid
graph TD
    User["👤 User (Longevity Coach / Individual)"]

    subgraph GoogleCloud [Google Cloud - External]
        GHealth[Google Fit / Health API]
        GTakeout[Google Takeout Export]
    end

    subgraph CloudReasoning [Frontier AI Cloud - Paid API]
        CloudAPI["☁️ Paid Frontier Model (Claude / Gemini)<br/>High-level Medical Reasoning & Guidelines"]
    end

    subgraph Host [Local Host - User Workspace]
        subgraph SyncEngine [local_counsel.health_sync]
            Connector[Health Connector]
            Mapper[openEHR Translator]
        end

        subgraph LocalDB [Local Medical Repository - Encrypted]
            EncStore["Encrypted openEHR Store<br/>(local_counsel.openehr.store)"]
            Crypto["Envelope Encryption<br/>scrypt KEK wraps AES-256-GCM DEK"]
            DB[("Per-user encrypted SQLite<br/>local_cache/health/&lt;user&gt;/openehr.db")]
            Vault["Encrypted credential<br/>(Google Health API key, same DEK)"]
            Archetypes[openEHR Archetypes & Templates - future OPT validation]

            EncStore -->|Encrypts via| Crypto
            EncStore -->|Persists ciphertext to| DB
            Vault -.->|stored in| DB
            EncStore -.->|future: validate against| Archetypes
        end

        subgraph Orchestration [Detailed Dify.ai AI Orchestration Layer]
            direction TB
            ChatUI["📱 Dify Chat WebApp (Chat Interface Provider)"]
            
            subgraph DifyCore [Dify Core Engine]
                Workflow["🔄 Dify Workflow & Agent Engine (Orchestrator)"]
                KB["📚 RAG Knowledge Base (Vector DB / Guidelines)"]
                Scheduler["⏰ Dify Scheduler (Scheduled Workflows / Cron)"]
                API["🔌 Dify API Endpoint (Triggered Workflows Hook)"]
            end

            subgraph DifyTools [Dify Workflow Tools]
                AQLTool["🧮 openEHR AQL Tool"]
                Anonymizer["🔒 Local Anonymizer Filter<br/>(Sanitizes PII & Medical IDs)"]
                PromptTool["📝 Prompt & API Connector"]
            end

            ChatUI -->|WebApp Events / Chat| Workflow
            Scheduler -->|Triggers scheduled sync| Workflow
            API -->|External webhooks| Workflow
            Workflow -->|RAG Retrieval| KB
            Workflow -->|Invokes AQL| AQLTool
            Workflow -->|Passes context| Anonymizer
            Anonymizer -->|Secured payload| PromptTool
        end

        subgraph Inference [Local Inference Backend]
            LLM["Local llama-server (Gemma-4-E2B)<br/>Optional Local Tasks / Backup"]
        end
    end

    User -->|Interacts with Chat UI| ChatUI
    Vault -.->|decrypt API key at trigger| Connector
    GHealth --> Connector
    GTakeout --> Connector
    Connector --> Mapper
    Mapper -->|Encrypted compositions| EncStore
    Scheduler -.->|Triggers sync run - passphrase unlock| Connector
    AQLTool -->|Query Requests| EncStore
    PromptTool -->|HTTPS Request (Anonymized)| CloudAPI
    Workflow -.->|Local Tasks| LLM
```

---

## 3. Data Ingestion Paths

To support both seamless syncing and zero-cloud setups, the system implements two connection paths:

### Path A: Automatic Local API Sync
* **Mechanism**: A Python script runs a localized OAuth 2.0 loopback server (`http://localhost:8085`) to acquire authorization tokens directly from the user's web browser.
* **API calls**: Direct REST calls to the `https://www.googleapis.com/fitness/v1/users/me/dataset/...` endpoints to retrieve physical activity, sleep periods, and heart rate logs.

### Path B: Offline Takeout Upload (Zero Cloud API Access)
* **Mechanism**: The user requests a Google Takeout export for Google Fit/Health, downloads the resulting ZIP, and drops it into a designated local directory (`local_cache/health_import/`).
* **Parser**: The local engine extracts the archive and parses the raw JSON files directly on disk.

---

## 4. openEHR Mapping Strategy

To ensure clinical standards, incoming Google Health data is translated into official openEHR templates:

| Google Health Data Point | target openEHR Archetype | template Composition |
| --- | --- | --- |
| **Daily Step Counts** | `openEHR-EHR-OBSERVATION.physical_activity.v0` | Physical Activity Tracker |
| **Heart Rate logs** | `openEHR-EHR-OBSERVATION.pulse.v2` | Vital Signs Composition |
| **Sleep Intervals / Quality** | `openEHR-EHR-OBSERVATION.sleep.v1` | Sleep Log Composition |
| **Body Composition (BIA)** — weight, BMI, body fat %, skeletal muscle, body water %, bone mass, BMR, visceral fat | `openEHR-EHR-OBSERVATION.body_weight.v2`, `...body_mass_index.v2`, `...body_composition.v0`, `...basal_metabolic_rate.v0` | Body Composition (BIA) Composition |

* **Translation Layer**: Written in Python (`local_counsel.openehr.mapper`), parsing the source fields into canonical openEHR Compositions. Note: values are currently mapped into recognizable archetype/element paths but **not yet validated against an Operational Template (OPT)** — that validation gate is future work (§7, `TODO.md`).
* **Storage Interface**: Compositions are encrypted (AES-256-GCM) and written directly to the per-user encrypted SQLite repository (§5.1) — not to an external EHRbase REST server.
* **Idempotency Strategy**: To prevent duplicate records during repeated sync runs, the sync engine generates a **deterministic UUIDv5** for each composition from the source record's stable ID and timestamp. Writing is an `INSERT OR REPLACE` keyed by that UID, so repeated syncs of the same data are safely idempotent.


---

## 5. Database Technology & Persistence

We have selected a **per-user, encrypted, persistent SQLite database** as the
storage engine for the local openEHR repository. Each user gets their own file at
`local_cache/health/<user_id>/openehr.db` (created `0700`/`0600`), implemented in
`local_counsel.openehr.store`.

* **Why Persistent instead of In-Memory?**
  An in-memory database would lose all health data history (step cycles, heart rate logs, and historical blood panels) every time the application is closed or the host machine restarts. Tracking biological age and longevity trends requires long-term, multi-year data persistence.
* **Why SQLite?**
  - **Zero-Dependency Setup:** SQLite requires no background daemons, local server configurations, or Docker dependencies. It is supported natively by Python (`import sqlite3`).
  - **Single-File Portability:** All medical data is stored in a single file (`openehr.db`), making backups, schema transfers, and data exports extremely easy.
  - **Performance:** For a single-user local application, SQLite easily handles thousands of records per second with a negligible memory footprint.
* **Why per-user files instead of multi-tenant tables?**
  A single-tenant file per user gives natural key isolation (one encryption key per file), a minimal blast radius, and no risk of cross-tenant query leakage. Multi-tenancy is intentionally avoided.

### 5.1 Encryption at Rest (envelope encryption)
Every clinical record — and every stored credential — is encrypted, implemented in
`local_counsel.openehr.crypto`:

* A **Key-Encryption Key (KEK)** is derived from the user's passphrase with the
  memory-hard **scrypt** KDF and a per-database random salt. The passphrase and KEK
  are never written to disk.
* A random 256-bit **Data-Encryption Key (DEK)** encrypts each openEHR composition
  with **AES-256-GCM**; only the DEK *wrapped by the KEK* is persisted, next to the
  salt and KDF parameters. The composition UID is bound in as GCM associated data so
  rows cannot be swapped between records or databases.
* **Stolen-file resistance:** without the passphrase, the file yields only
  ciphertext and an unopenable wrapped key. A wrong passphrase / different user fails
  the GCM authentication tag and is rejected before any data is touched.
* **Passphrase rotation** only re-wraps the DEK — records are never re-encrypted.

> Note: this replaces the earlier plan of delegating storage to an external EHRbase
> server (§6.2). We persist canonical openEHR compositions directly in the encrypted
> SQLite file. OPT/AQL validation against a real EHRbase remains future work — see
> `TODO.md` and §7.

---

## 6. Security, Privacy & Access Control

### 6.1 Credential Isolation
* Client secrets, API tokens, and OAuth refresh tokens (e.g. the **Google Health / Fit API key**) are stored **encrypted inside the per-user repository under the same DEK** as clinical data (`store.put_secret` / `get_secret`), not in plaintext.
* Because credentials are encrypted with the user key, **retrieval requires unlocking the store first**: the passphrase gateway sits at the BIA **retrieval trigger** (`health_sync.sync.trigger_bia_sync`) — unlock → decrypt API key → fetch. A wrong passphrase aborts before any network or credential access.
* A git-ignored `.env` may still bootstrap non-secret configuration, but long-lived secrets live encrypted at rest.

### 6.2 Database Isolation
* The repository is a local, per-user file; there is no network-exposed database service to authenticate against. (An earlier design delegated storage to a loopback `EHRbase` with Basic Auth; the current implementation encrypts the SQLite file directly instead — see §5.1.)

### 6.3 Privacy-Preserving Hybrid Cloud (Anonymization Filter)
To ensure the highest safety and scientific depth, the Longevity Mentor utilizes a **paid external Frontier Model** (a current frontier model, e.g. Claude or Gemini) for high-level reasoning and research analysis. To guarantee absolute data privacy and compliance with GDPR, the following security measures are implemented:

* **Local Anonymization Filter (PII Scrubbing)**: Before any prompt leaves the local machine, a dedicated tool in the Dify workflow scrubs all Personally Identifiable Information (PII) including:
  * Names, email addresses, phone numbers, and home addresses.
  * Medical identification numbers and database record IDs.
  * Exact dates (replaced with relative offsets, e.g., "Day 1, Day 2").
  * Exact Age (fuzzed dynamically by introducing a random +/- 15% variance offset to prevent database cross-matching re-identification). *Implemented for the BIA nutrition path in `health_sync.nutrition.SubjectProfile.fuzzed_age_band` / `build_nutrition_prompt`: sex is included and the age is emitted only as a ±15% band, never exactly.*
* **Anonymized Payload**: The external cloud API only receives raw, desensitized biometric metrics (e.g. "Male, Age 40 (fuzzed to 36-46 range), average RHR 58 bpm, average deep sleep 1.2h") and general health queries, ensuring no identifiable medical record can ever enter the external cloud provider's systems or training logs.
* **Local Fallback (Air-gapped mode)**: In high-security environments, the system can be configured to toggle off the cloud API and fall back to the **local llama-server** running `Gemma-4-E2B` for simple local metrics checks.

---

## 7. Preprocessing Non-openEHR Sources (LLM-Assisted Mapping) — TODO

**Status: planned, not yet implemented.**

Not every source field has a canonical openEHR target. Consumer devices emit
**proprietary / vendor-namespaced** metrics (e.g. BIA scales exposing skeletal
muscle mass, body-water %, visceral-fat rating, BMR under `com.withings.*` or
other non-standard streams) that fall outside Google Fit's first-class types and
have no obvious archetype. Before such **external, non-medical, non-openEHR data**
can enter the repository, it must be preprocessed into standards-valid
compositions.

### 7.1 Proposal: a local "Mapping Assistant" (Gemma), advisory by design
Reuse the advisory pattern from the OKF semantic reviewer (`okf_review.py`): the
**local `Gemma-4-E2B`** model *drafts* mappings but never writes to the EHR
directly. For each **unknown source field**, the model proposes:
* target **archetype + element path** (e.g. `openEHR-EHR-OBSERVATION.body_weight.v2`),
* the **unit conversion** required (kg↔lb, %↔ratio),
* a **confidence score** (e.g. `HIGH | MEDIUM | LOW`, mirroring the `PASS/FLAG/INCONCLUSIVE` verdict style), and
* a short **rationale**.

### 7.2 Deterministic gate + confidence routing (non-negotiable)
The LLM proposal is only a candidate. It is always followed by a deterministic
check and confidence-based routing:
1. **Schema validation:** build the candidate composition and validate it against
   the openEHR Operational Template (OPT/JSON schema). *Invalid → rejected,
   regardless of confidence.*
2. **Route by confidence:** `HIGH` + schema-valid → auto-map; `MEDIUM/LOW` /
   novel / schema-ambiguous → **human-in-the-loop (HITL) review queue**.
3. **Human approval** for the uncertain tail. Ties to the Safety Filtering
   requirement — medical data mapping requires explicit human oversight.

### 7.3 Mapping registry (run the model once per field, not per record)
Approved mappings are cached in a persistent **mapping registry** keyed by
`(vendor, source_field, unit)`. The LLM is invoked only for *novel* fields; all
subsequent records reuse the approved deterministic mapping. This keeps ingestion
**reproducible, cheap, and idempotent**, and consistent with the deterministic
UUIDv5 strategy in §4.

### 7.4 Why not trust the LLM directly
Silent errors in medical data are dangerous: hallucinated **unit conversions**
and wrong **archetype selection** would corrupt the record without failing
loudly. Confidence scoring + schema validation + HITL review bound this risk.

### TODO checklist
- [ ] Add a **body-composition (BIA) row** to the §4 mapping table (candidate archetypes: `body_weight.v2`, `body_mass_index.v2`, plus a fat/muscle/water archetype) so known fields need no LLM.
- [ ] Define the confidence verdict schema and the Gemma mapping prompt (one field per call; keep within the small-model context budget, as in `okf_review.py`).
- [ ] Implement the deterministic OPT/JSON-schema validation gate.
- [ ] Implement the persistent **mapping registry** and cache lookup keyed by `(vendor, field, unit)`.
- [ ] Implement the **HITL review queue** (present proposal + rationale + confidence; capture approve/edit/reject).
- [ ] Extend the E2E to cover: proprietary field → Mapping Assistant → validate → (HITL if needed) → openEHR composition stored.
- [ ] Log every auto-mapping and human decision for auditability.

