---
type: Installation Guide
title: Installer Subproject
description: How the build, provision, boot, test, and deployment pipeline is implemented with nox in the repository root.
tags: [installer, pipeline, nox]
timestamp: 2026-07-11T11:00:00+02:00
---

# Installer Subproject

The build, provisioning, boot, test, and deployment pipeline is implemented with [**nox**](https://nox.thea.codes/): the session definitions live in the repository root [`noxfile.py`](../noxfile.py) and the underlying ops logic in the sibling `pipeline/` package — this directory is a placeholder and carries no separate pipeline logic.

This pipeline automates and supports setup, execution, and verification for both the **Erasmus+ Compliance Assistant** and the **Longevity Mentor** workflows.

## Main sessions

| Session | Purpose | Erasmus+ Application | Longevity Mentor Application |
| --- | --- | --- | --- |
| `provision` | Idempotently download + extract dependencies. | Downloads GGUF model + llama.cpp + AnythingLLM. | Same shared backend and model assets. |
| `boot_llm` | Start `llama-server` and wait until it is ready. | Starts the local inference server for document audits. | Starts the server for local fallback checks. |
| `run` | Boot the LLM (if needed) and run the assistant. | Runs the interactive CLI document compliance review. | (Runs the default CLI tool). |
| `okf` | Verify the docs are a conformant OKF v0.1 bundle. | Validates Erasmus+ requirement concepts. | Validates Longevity Mentor requirement concepts. |
| `okf_semantic` | Advisory LLM review of the docs (slow). | Advisory review of project documentation. | Advisory review of health/architecture documentation. |
| `unit` | Run the fast, LLM-free unit tests. | Runs parser and config validation tests. | Runs openEHR mapper, envelope encryption (scrypt + AES-256-GCM), and SQLite storage tests. |
| `test` | Boot the LLM (if needed) and run integration tests. | Verifies LLM-assisted compliance checks. | Verifies the E2E BIA health sync mapping, encrypted storage, PII scrubbing, and AI advice flow. |
| `stop_llm` | Stop the server and its child processes. | Cleans up the background `llama-server`. | Cleans up the background `llama-server`. |
| `ui` | Launch the AnythingLLM desktop UI. | Provides a desktop chat workspace for documents. | Can be used as a local chat interface. |
| `dify` / `boot_dify` | Launch the Dify workflow stack via Docker Compose. | Orchestrates document workflows, RAG, and audits. | Drives scheduled syncs, anonymizer filters, and chat. |
| `e2e` | Final validation stage (default): browser end-to-end tests **through Dify**, headless. Provisions Dify + Gemma 4 (needs Docker). | — | Drives parse → encrypted openEHR → anonymize → Dify → Gemma 4 advice, and a Dify chat greeting, in a real browser. |
| `demo` | The same E2E tests headed + slow-motion with on-screen narration (Play/Pause/Next), for live demos. | — | Human-paced walkthrough; per-file + `--slowmo`/`--takeout-zip`/`--manual` via `--`. |

Run `nox -l` to list every session. For the full design and setup see the root [`README.md`](../README.md) and [`docs/core/ARCHITECTURE.md`](../docs/core/ARCHITECTURE.md).
