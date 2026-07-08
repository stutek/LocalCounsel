---
type: Installation Guide
title: Installer Subproject
description: How the build, provision, boot, test, and deployment pipeline is implemented with nox in the repository root.
tags: [installer, pipeline, nox]
timestamp: 2026-07-08T00:00:00+02:00
---

# Installer Subproject

The build, provisioning, boot, test, and deployment pipeline is implemented with
[**nox**](https://nox.thea.codes/): the session definitions live in the
repository root [`noxfile.py`](../noxfile.py) and the underlying ops logic in
the sibling `pipeline/` package — this directory is a placeholder and carries no
separate pipeline logic.

## Main sessions

| Session | Purpose |
| --- | --- |
| `provision` | Idempotently download + extract the model, llama.cpp, and AnythingLLM. |
| `boot_llm` | Start `llama-server` and wait until it is ready. |
| `run` | Boot the LLM (if needed) and run the assistant. |
| `okf` | Verify the docs are a conformant OKF v0.1 knowledge bundle. |
| `okf_semantic` | Advisory LLM review of the docs (boots the LLM; never gates the build). |
| `unit` | Run the fast, LLM-free unit tests. |
| `test` | Boot the LLM (if needed) and run the integration tests. |
| `stop_llm` | Stop the server and its child processes. |
| `ui` | Launch the AnythingLLM desktop UI. |

Run `nox -l` to list every session. For the full design and setup see the root
[`README.md`](../README.md) and [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).
