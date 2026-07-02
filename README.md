---
type: Project Overview
title: LocalCounsel
description: Local-first compliance assistant that reviews documents against Erasmus+, GDPR, and EU AI Act using a pluggable local LLM.
tags: [overview, readme, compliance, local-first]
timestamp: 2026-06-30T23:39:47+02:00
---

# LocalCounsel

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A **local-first compliance assistant** that reviews documents and reports against
regulatory frameworks (Erasmus+, GDPR, EU AI Act), generates evaluation reports,
and supports partner consultations — all running **entirely on your own machine**
so sensitive data never leaves your infrastructure.

The LLM is **pluggable**: the app talks to a local OpenAI-compatible
`llama-server`, so the underlying model (Gemma, DeepSeek, …) is swapped by
booting a different GGUF — no code changes.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design and
[requirements/requirements.md](requirements/requirements.md) for requirements.

## Stack

| Layer | Choice |
| --- | --- |
| Automation pipeline | **nox** (`noxfile.py`) |
| Inference backend | **llama.cpp** + a pluggable GGUF model |
| RAG + UI engine | **AnythingLLM** Desktop |
| Compliance logic | **Python** + the `openai` client |

## Requirements

- Python 3.10+
- [`nox`](https://nox.thea.codes/) — `pipx install nox` (or `pip install nox`)
- Linux x64 (the pinned llama.cpp binary and AnythingLLM AppImage target Ubuntu x64)

## Usage

```bash
nox -s provision   # idempotently download model + llama.cpp + AnythingLLM
nox -s boot_llm    # start llama-server and wait until it is ready
nox -s run         # boot the LLM (if needed) and run the assistant
nox -s test        # boot the LLM (if needed) and run the integration tests
nox -s okf         # verify the docs are a conformant OKF v0.1 bundle
nox -s stop_llm    # stop the server and its child processes
nox -s ui          # launch the AnythingLLM desktop UI
```

Running bare `nox` runs the default sessions — `okf` (fast, no LLM) then `test`.

The first `provision`/`boot_llm` downloads several GB (model weights + binaries)
into `build/` (gitignored). Subsequent runs reuse the cache.

## Configuration

All settings are environment-overridable. To run a **different model**, point the
pipeline at another GGUF and update the logical model name:

| Variable | Default | Purpose |
| --- | --- | --- |
| `LC_MODEL_URL` | Gemma-2-2b-it Q4_K_M GGUF | Model weights to download |
| `LC_MODEL_NAME` | `gemma` | Logical name sent to the API |
| `LC_LLAMA_URL` | pinned llama.cpp release | Inference backend binaries |
| `LC_LLM_HOST` / `LC_LLM_PORT` | `127.0.0.1` / `8080` | Server bind address |
| `LC_LLM_TIMEOUT` | `300` | Client timeout (seconds) |

Example — run a different model:

```bash
LC_MODEL_URL="https://…/some-model.gguf" LC_MODEL_NAME="deepseek" nox -s run
```

## Compliance posture

The LLM is used strictly as **decision-support with a human in the loop** on every
gateway and final decision, keeping the system out of the EU AI Act high-risk
category. Running fully locally keeps processing GDPR-friendly. Final
classification for any concrete deployment requires legal/DPO review — see
[docs/final-report-llm-eu-ai-act.md](docs/final-report-llm-eu-ai-act.md).

## Knowledge bundle (OKF)

This repository doubles as an [Open Knowledge Format (OKF) v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
bundle, so AI agents (and humans) can consume the project's curated knowledge
without any custom integration — the file system *is* the API.

- Every non-reserved Markdown file is an OKF **concept**: it carries YAML
  frontmatter with a required `type` field, plus `title`, `description`, `tags`,
  and a `timestamp`. A concept's **ID** is its path with the `.md` removed
  (e.g. `docs/ARCHITECTURE`).
- [`index.md`](index.md) is the bundle listing — the entry point mapping every
  Concept ID to its type and description.

Keeping this bundle conformant is a project requirement — see the
**OKF-Compliant Knowledge Bundle** NFR in
[requirements/requirements.md](requirements/requirements.md#4-non-functional--architectural-requirements).
When you add or rename a Markdown doc, give it frontmatter with a `type` and add
it to [`index.md`](index.md), then run `nox -s okf` to check conformance (it also
runs by default as part of bare `nox`, so CI catches regressions).

## License

LocalCounsel is released under the [MIT License](LICENSE) — an
[OSI-approved](https://opensource.org/licenses/MIT) license that conforms to the
[Open Definition](https://opendefinition.org/). You are free to use, modify, and
redistribute both the source code and the documentation, provided the copyright
notice and permission notice are retained.

Contributions are accepted under the same license.
