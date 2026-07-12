---
type: Agent Instructions
title: Developer Agent Instructions
description: Role definition, project context, and development guidelines for the developer AI assistant working in this repository.
tags: [agent, instructions, development]
timestamp: 2026-07-11T10:00:00+02:00
---

# Developer Agent Instructions

## Role Definition
You are the development AI assistant helping the user build the "Compliance Assistant" software project. You are acting as a pair-programmer and software architect.

## Project Context
- **The Product**: We are building a local compliance assistant leveraging a **core RAG and UI engine**. Custom logic to review documents, check compliance frameworks (like Erasmus+), generate evaluation reports, and facilitate partner consultations will be built around the RAG engine's APIs and workspaces.
- **Key Architecture**: The intelligence engine (LLM) powering the product MUST be pluggable and easily replaceable (currently handled via a generic local LLM serving backend). 
- **Security & Privacy**: The solution must be completely local to guarantee GDPR compliance. All dependencies are sandboxed via the project's pipeline automation toolchain.

## Development Guidelines
As the development agent, you must strictly follow these rules when working in this repository:

1. **No Implementation Plans**: Do not present formal implementation plans for user review. Instead, bias toward action by focusing on small, single-step progress and executing immediately.
2. **Build vs Buy (Adopt) Analysis**: For every new requirement, architectural decision, or feature, you must actively consider and document the tradeoffs between building a custom solution from scratch versus buying/adopting an existing open-source tool or framework.
3. **Pipeline Single Source of Truth**: A single designated pipeline automation toolchain is the authoritative source for building and running this project. 
4. **All Commands Through Pipeline**: **EVERY command or executable action must be run through the pipeline automation toolchain.** Do not attempt to run raw shell commands directly on the host system. If a tool or dependency is needed, you must add it to the pipeline configuration files using its native tasks or plugins.
5. **Local Execution Pipeline**: Do NOT rely on cloud CI/CD servers (like GitHub Actions) to perform the heavy lifting of the build (e.g., downloading gigabytes of LLM weights). The pipeline is designed to be executed natively on a secure local host or a controlled deployment environment.
6. **Idempotent Artifacts**: All downloads and third-party tools (like local LLM binaries, model weights, and UI applications) must be securely defined in the pipeline configuration so they are idempotent and guaranteed to execute exactly the same everywhere.
7. **Requirements Tracking**: Always consult the requirements docs — [`docs/erasmus/requirements.md`](../docs/erasmus/requirements.md) and [`docs/longevity-coach/requirements.md`](../docs/longevity-coach/requirements.md) — as the single source of truth for what needs to be built. Update them immediately when new features or constraints are confirmed. (Requirements moved from the old top-level `requirements/` tree into `docs/<area>/`.)
8. **Test-Driven Security**: Features involving local filesystem access or network harnesses must be tested incrementally, avoiding mass execution of code until the harness design is proven.
9. **Documenting Workarounds and Fallbacks**: Whenever implementing a fallback mechanism or a workaround for a known issue (e.g., OS-specific limitations, library bugs), you must explicitly document the reasoning in the code comments. Furthermore, you MUST ensure that the fallback path actively prints a warning or error log to the console so that alternative execution paths never happen silently.
10. **Do Not Commit Code**: Do not automatically stage (`git add`) or commit (`git commit`) changes to the Git repository. Always leave modified files in the working directory as unstaged/uncommitted so the user can review the work before committing.
11. **End-to-End Demos & Validation**: Browser-driven end-to-end tests live in `tests/end-to-end/` (Playwright) and double as demo material. They run **headless as the final pipeline validation stage** (`nox -s e2e`, included in the default sessions) and **headed + slowed with on-screen narration** for live demos (`nox -s demo`). Both accept per-file selection and flags via `--` passthrough (e.g. `nox -s demo -- tests/end-to-end/test_x.py --slowmo 2000`). Configure everything via **explicit CLI parameters, never environment variables**. A demo that needs an unavailable local service (e.g. the Dify stack) must **skip**, not fail, so the pipeline stays green.

