---
type: Project Overview
title: LocalCounsel
description: Local-first assistant supporting Erasmus+ compliance audits and privacy-preserving Longevity Mentor health-data coaching.
tags: [overview, readme, compliance, local-first, longevity, health, erasmus-plus]
timestamp: 2026-07-11T11:00:00+02:00
---

# LocalCounsel

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A **local-first compliance and coaching assistant** designed to run fully local, privacy-preserving workflows. It supports two primary use cases:

1. **Erasmus+ Compliance Assistant**: Reviews application documents, project reports, and financial templates against Erasmus+ rules, helping contract managers and financial controllers flag compliance issues and generate evaluation reports.
2. **Longevity Mentor**: Ingests Google Health/Fit records, parses lifestyle and biometric logs, maps them to standard openEHR schemas, and persists them to an encrypted local SQLite database. It compares metrics against longevity science benchmarks and provides science-backed educational advice using a local LLM or an optional anonymized (PII-scrubbed, fuzzed age) external frontier model.

All processing is **local by default**. Raw, identifiable data never leaves your machine.

The local LLM is **pluggable**: the application communicates with an OpenAI-compatible local `llama-server` (powered by `llama.cpp`), allowing the underlying model (Gemma, DeepSeek, etc.) to be swapped by simply booting a different GGUF file.

For advanced workflows (such as scheduled syncs, local RAG databases, the **PII-scrubbing anonymizer** filter, and the chat web interfaces), LocalCounsel uses a self-hosted **[Dify.ai](https://dify.ai)** stack launched via Docker Compose (`nox -s dify`).

See [docs/core/ARCHITECTURE.md](docs/core/ARCHITECTURE.md) for the main system design, [docs/longevity-coach/health-integration-architecture.md](docs/longevity-coach/health-integration-architecture.md) for the Longevity Mentor architecture, and [index.md](index.md) for the OKF bundle entry point.

## Stack

| Layer | Choice |
| --- | --- |
| Automation pipeline | **nox** (`noxfile.py`) |
| Inference backend | **llama.cpp** + a pluggable GGUF model (default: Gemma-4-E2B-it) |
| Orchestration & workflows | **Dify.ai** (self-hosted via Docker Compose) — chat UI, RAG database, scheduler, PII anonymizer |
| Desktop RAG UI (optional) | **AnythingLLM** Desktop |
| Medical Storage (Longevity) | **Encrypted Local SQLite** — persists standard **openEHR** compositions |
| Cryptography (Longevity) | **Envelope Encryption** via Python `cryptography` (scrypt KDF + AES-256-GCM) |
| Compliance/Advice Logic | **Python** + `openai` client |

## Requirements

- Python 3.10+
- [`nox`](https://nox.thea.codes/) — `pipx install nox` (or `pip install nox`)
- Linux x64 — the primary supported target (pinned llama.cpp binary + AnythingLLM
  AppImage). macOS (arm64/x64) download paths exist and are best-effort. Windows
  is currently **not supported** (stubbed).
- **Docker + Docker Compose** — for the self-hosted Dify.ai stack and the
  end-to-end demo stage (`nox -s dify`, `demo`, `e2e`, all of which provision Dify);
  not needed for `unit`, `run`, or the CLI.

## Usage

```bash
nox -s provision   # Idempotently download model + llama.cpp + AnythingLLM
nox -s boot_llm    # Start llama-server and wait until it is ready
nox -s run         # Boot the LLM (if needed) and run the assistant
nox -s test        # Boot the LLM (if needed) and run integration tests (including Longevity E2E)
nox -s okf         # Verify the docs are a conformant OKF v0.1 bundle
nox -s okf_semantic  # Advisory LLM review of the docs (boots the LLM; slow)
nox -s unit        # Run the fast, LLM-free unit tests (encryption, openEHR mapping, etc.)
nox -s stop_llm    # Stop the server and its child processes
nox -s ui          # Launch the AnythingLLM desktop UI
nox -s dify        # Launch the self-hosted Dify.ai workflow stack (Docker Compose; boots the LLM)
nox -s boot_dify   # Start the Dify.ai stack + local LLM
nox -s stop_dify   # Stop the Dify.ai Docker Compose stack
nox -s e2e         # Final validation: browser E2E through Dify, headless (provisions Dify + Gemma 4)
nox -s demo        # Same E2E tests, headed + slow-mo with narration (live demo; provisions Dify)
```

Running bare `nox` runs the default sessions — `okf`, `unit`, `test`, then `e2e`
(the browser end-to-end tests as the final validation stage). Both end-to-end tests
run **through the Dify stack** (Dify → local Gemma 4); the `demo`/`e2e` sessions
provision Dify and install Playwright + Chromium on first run, so they **require Docker**.

The first `provision`/`boot_llm` downloads several GB (model weights + binaries)
into `build/` (gitignored). Subsequent runs reuse the cache.

### Verifying the Workflows
- **Erasmus+ Compliance checks**: The `run` session invokes the custom assistant logic on local files.
- **Longevity Mentor BIA — end-to-end demos**: Browser-driven E2E tests in [`tests/end-to-end/`](tests/end-to-end/) drive the full scenario (parse a real Google Health/Beurer export → encrypted openEHR → anonymized prompt → **through Dify → local Gemma 4** advice), plus a demo that greets the Dify Longevity Mentor chat app. The `demo`/`e2e` sessions provision the Dify stack themselves. They run headless as the final pipeline stage (`nox -s e2e`) and headed + narrated as a live demo (`nox -s demo`). Configure via explicit params after `--`, selectable per file or shortcut:
  ```bash
  nox -s demo -- dify                  # run only the Dify greeting demo
  nox -s demo -- nutrition             # run only the Nutrition/openEHR demo
  nox -s demo -- dify --debug          # run Dify demo starting paused (step-by-step with overlay controls)
  nox -s demo -- --pause               # drop into the Playwright Inspector step-by-step
  ```
- **Local Unit Tests**: `nox -s unit` runs isolated validation tests for the openEHR mapper, envelope crypto, SQLite storage, the Takeout parser, and anonymization — without needing the local LLM running.

## Configuration

All settings are environment-overridable. To run a **different model**, point the
pipeline at another GGUF and update the logical model name:

| Variable | Default | Purpose |
| --- | --- | --- |
| `LC_MODEL_URL` | Gemma-4-E2B-it Q4_K_M GGUF | Model weights to download |
| `LC_MODEL_NAME` | `gemma` | Logical name sent to the API |
| `LC_LLAMA_URL` | pinned llama.cpp release | Inference backend binaries |
| `LC_LLM_HOST` / `LC_LLM_PORT` | `127.0.0.1` / `8080` | Server bind address |
| `LC_LLM_TIMEOUT` | `300` | Client timeout (seconds) |
| `LC_DIFY_URL` | pinned Dify.ai release (1.15.0) | Dify workflow stack source |

Example — run a different model:

```bash
LC_MODEL_URL="https://…/some-model.gguf" LC_MODEL_NAME="deepseek" nox -s run
```

## Compliance posture

- **Erasmus+**: The LLM is used strictly as **decision-support with a human in the loop** on every gateway and final decision, keeping the system out of the EU AI Act high-risk category. Running fully locally keeps processing GDPR-friendly. See [docs/erasmus/final-report-llm-eu-ai-act.md](docs/erasmus/final-report-llm-eu-ai-act.md).
- **Longevity Mentor**: Processing of private biometric/health records is kept strictly local using local-first storage and database envelope encryption (derived from the user's passphrase). External cloud reasoning uses a zero-trust model: the local anonymizer filter dynamically scrubs PII, strips exact calendar dates, and fuzzes the subject's exact age (introducing a +/- 10% variance (single randomized offset)) to prevent medical database re-identification before sending data to external APIs. In air-gapped mode, it falls back to the local `llama-server` running Gemma-4-E2B. All coaching output is explicitly tagged as educational guidance, not medical advice.

## Knowledge bundle (OKF)

This repository doubles as an [Open Knowledge Format (OKF) v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
bundle, so AI agents (and humans) can consume the project's curated knowledge
without any custom integration — the file system *is* the API.

- Every non-reserved Markdown file is an OKF **concept**: it carries YAML
  frontmatter with a required `type` field, plus `title`, `description`, `tags`,
  and a `timestamp`. A concept's **ID** is its path with the `.md` removed
  (e.g. `docs/core/ARCHITECTURE`).
- [`index.md`](index.md) is the bundle listing — the entry point mapping every
  Concept ID to its type and description.

Keeping this bundle conformant is a project requirement. When you add or rename a Markdown doc, give it frontmatter with a `type` and add it to [`index.md`](index.md), then run `nox -s okf` to check conformance (it also runs by default as part of bare `nox`, so CI catches regressions). For requirements, see [docs/erasmus/requirements.md](docs/erasmus/requirements.md) and [docs/longevity-coach/requirements.md](docs/longevity-coach/requirements.md).

## License

LocalCounsel is released under the [MIT License](LICENSE) — an
[OSI-approved](https://opensource.org/licenses/MIT) license that conforms to the
[Open Definition](https://opendefinition.org/). You are free to use, modify, and
redistribute both the source code and the documentation, provided the copyright
notice and permission notice are retained.

Contributions are accepted under the same license.
