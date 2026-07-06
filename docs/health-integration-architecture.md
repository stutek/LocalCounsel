---
type: Architecture
title: Architecture — Google Health to openEHR Sync
description: System design for local Google Health/Fit data ingestion, openEHR mapping, and secure local storage.
tags: [architecture, design, health, openEHR, privacy]
timestamp: 2026-07-06T13:42:00+02:00
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

        subgraph LocalDB [Local Medical Repository]
            EHRbase["Local openEHR Server (REST API, AQL & Validation)"]
            DB[("Persistent SQLite Database (openehr.db)")]
            Archetypes[openEHR Archetypes & Templates]
            
            EHRbase -->|Validates against| Archetypes
            EHRbase -->|Persists data to| DB
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
            LLM["Local llama-server (Gemma-2-2b)<br/>Optional Local Tasks / Backup"]
        end
    end

    User -->|Interacts with Chat UI| ChatUI
    GHealth --> Connector
    GTakeout --> Connector
    Connector --> Mapper
    Mapper -->|POST Compositions| EHRbase
    Scheduler -.->|Triggers sync run| Connector
    AQLTool -->|AQL Query Requests| EHRbase
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

* **Translation Layer**: Written in Python, parsing the source fields and validating them against JSON schemas generated from openEHR Operational Templates (OPT).
* **Storage Interface**: Data is pushed via REST HTTP headers containing canonical openEHR Compositions to the local EHRbase server.
* **Idempotency Strategy**: To prevent duplicate records during repeated sync runs, the sync engine generates a **deterministic UUIDv5** for each composition using the source Google Health record's unique ID and timestamp. Before writing, the server uses a `PUT /composition/{uid}` endpoint (or checks for existing UID), ensuring that repeated syncs of the same data are safely idempotent.


---

## 5. Database Technology & Persistence

We have selected a **Persistent SQLite Database** (`local_cache/openehr.db`) as the storage engine for the local openEHR server:

* **Why Persistent instead of In-Memory?**
  An in-memory database would lose all health data history (step cycles, heart rate logs, and historical blood panels) every time the application is closed or the host machine restarts. Tracking biological age and longevity trends requires long-term, multi-year data persistence.
* **Why SQLite?**
  - **Zero-Dependency Setup:** SQLite requires no background daemons, local server configurations, or Docker dependencies. It is supported natively by Python (`import sqlite3`).
  - **Single-File Portability:** All medical data is stored in a single file (`openehr.db`), making backups, schema transfers, and data exports extremely easy.
  - **Performance:** For a single-user local application, SQLite easily handles thousands of records per second with a negligible memory footprint.

---

## 6. Security, Privacy & Access Control

### 6.1 Credential Isolation
* Client secrets, API tokens, and OAuth refresh tokens are stored exclusively in the local, git-ignored `.env` file or `~/.config/local_counsel/`.

### 6.2 Database Isolation
* The local `EHRbase` runs on loopback `127.0.0.1` and requires Basic Authentication. The credentials are randomly generated during the `nox -s provision` phase and saved locally.

### 6.3 Privacy-Preserving Hybrid Cloud (Anonymization Filter)
To ensure the highest safety and scientific depth, the Longevity Mentor utilizes a **paid external Frontier Model** (like Claude 3.5 Sonnet or Gemini 1.5 Pro) for high-level reasoning and research analysis. To guarantee absolute data privacy and compliance with GDPR, the following security measures are implemented:

* **Local Anonymization Filter (PII Scrubbing)**: Before any prompt leaves the local machine, a dedicated tool in the Dify workflow scrubs all Personally Identifiable Information (PII) including:
  * Names, email addresses, phone numbers, and home addresses.
  * Medical identification numbers and database record IDs.
  * Exact dates (replaced with relative offsets, e.g., "Day 1, Day 2").
  * Exact Age (fuzzed dynamically by introducing a random +/- 15% variance offset to prevent database cross-matching re-identification).
* **Anonymized Payload**: The external cloud API only receives raw, desensitized biometric metrics (e.g. "Male, Age 40 (fuzzed to 36-46 range), average RHR 58 bpm, average deep sleep 1.2h") and general health queries, ensuring no identifiable medical record can ever enter the external cloud provider's systems or training logs.
* **Local Fallback (Air-gapped mode)**: In high-security environments, the system can be configured to toggle off the cloud API and fall back to the **local llama-server** running `Gemma-2-2b` for simple local metrics checks.

