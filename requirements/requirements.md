---
type: Requirements
title: Compliance Assistant Requirements
description: Functional and non-functional requirements for the LocalCounsel compliance assistant.
tags: [requirements, compliance]
timestamp: 2026-06-30T23:28:34+02:00
---

# Compliance Assistant Requirements

## 1. Project Overview
A local assistant designed to review documents and reports, check for compliance against specific frameworks, generate evaluation reports, and facilitate partner consultations.

The assistant is built to **support contract managers (*skrbniki pogodbe*) and financial controllers (*finančni nadzorniki*)** in the supported processes (application evaluation, project monitoring, and final report evaluation). These processes are modelled as BPMN-style diagrams in [docs/erasmus-processes.md](../docs/erasmus-processes.md).

## 2. Use Cases
Specific use cases and their detailed requirements are documented in the `use_cases/` folder:
- [Erasmus+ Contract Management](use_cases/erasmus_plus.md)

## 3. Functional Requirements
- **Document Review**: Ability to ingest, parse, and extract information from various document formats.
- **Compliance Checking**: Cross-reference extracted document contents against predefined compliance rules based on the active use case.
- **Report Generation**: Automatically generate comprehensive evaluation reports detailing compliance status, highlighted issues, and action items.
- **Partner Consultation**: Provide a workflow or interface to consult partners regarding findings, clarify ambiguities, or request missing documentation.

## 4. Non-Functional / Architectural Requirements

> **Regulatory baseline**: **GDPR** and the **EU AI Act** are foundational,
> non-negotiable NFRs. Every feature must be designed and reviewed against both
> from the start, not retrofitted.

- **Core UI and RAG Engine**: The application relies on a comprehensive, adopted document management, RAG (Retrieval-Augmented Generation), and user interface engine. Custom compliance logic, report generation, and partner consultation workflows will be built as integrations or scripts that interact with this engine's API/Workspaces, rather than building a custom chat UI from scratch.
- **Pluggable Intelligence Engine**: The underlying Large Language Model (LLM) MUST be pluggable and easily replaceable. The default engine will be a localized, quantized model served via a high-performance local inference backend. The Core UI engine handles the LLM abstraction, allowing future swaps.
- **Incremental Development**: System architecture must be modular to support incremental feature additions over time.
- **Regression Testing**: The system must include a robust regression testing suite to ensure that compliance logic and document parsing remain stable across updates and model swaps.
- **GDPR Compliance & Data Privacy** *(baseline NFR)*: The solution must be fully GDPR compliant. The purely local AI integration guarantees that sensitive data never leaves the user's infrastructure, drastically simplifying compliance. In particular, no compliance outcome may rest on a solely automated decision with legal or significant effect (GDPR Art. 22) — a human stays in the loop on all decisions.
- **EU AI Act Compliance** *(baseline NFR)*: The solution must comply with the EU AI Act. The LLM is used strictly as **decision-support** with **human-in-the-loop** on every gateway and final decision, keeping the system out of the high-risk category. AI-generated content (drafts, feedback letters) must be marked as AI-generated and carry human editorial responsibility (Art. 50). The per-stage risk mapping and constraints are documented in [../docs/final-report-llm-eu-ai-act.md](../docs/final-report-llm-eu-ai-act.md). Final classification for any concrete deployment requires legal/DPO review.
- **Security & Sandboxing**: The solution must be highly secure. The application must run under a dedicated, unprivileged user account to enforce strict filesystem access controls. The RAG engine and the LLM inference backend run completely sandboxed.
- **Rapid Demo Provisioning**: A demo environment must be able to start up in a few minutes using a single command. The designated automated pipeline toolchain handles the creation of the sandbox, idempotent downloading of the RAG engine and local LLM binaries, and initialization without manual intervention.
- **OKF-Compliant Knowledge Bundle**: The repository's documentation must remain a conformant [Open Knowledge Format (OKF) v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) bundle so that AI agents can consume the project's curated knowledge without custom integration. Every non-reserved Markdown file MUST carry YAML frontmatter with a non-empty `type` field (plus, where applicable, `title`, `description`, `tags`, and a `timestamp`), and a root [`index.md`](../index.md) MUST list the concepts. New or renamed Markdown docs must preserve conformance.
