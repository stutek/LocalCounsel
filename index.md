# LocalCounsel — OKF Knowledge Bundle

This repository is an [Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
v0.1 bundle: every non-reserved Markdown file is an OKF *concept* carrying YAML
frontmatter with a required `type` field. A concept's ID is its file path with the
`.md` suffix removed.

## Concepts

| Concept ID | Type | Description |
| --- | --- | --- |
| [/README](/README.md) | Project Overview | Local-first compliance assistant that reviews documents against Erasmus+, GDPR, and EU AI Act using a pluggable local LLM. |
| [/TODO](/TODO.md) | Backlog | Consolidated backlog of known gaps, weaknesses, and risks across health-sync, openEHR persistence, encryption, anonymization, and AI advice. |
| [/docs/core/ARCHITECTURE](/docs/core/ARCHITECTURE.md) | Architecture | System design: components, startup flow, review workflow, LLM pluggability. |
| [/docs/erasmus/requirements](/docs/erasmus/requirements.md) | Requirements | Functional and non-functional requirements for the Erasmus+ assistant. |
| [/docs/erasmus/use_cases/erasmus_plus](/docs/erasmus/use_cases/erasmus_plus.md) | Use Case | Contract and execution management use case for Erasmus+ projects. |
| [/docs/erasmus/erasmus-processes](/docs/erasmus/erasmus-processes.md) | Process Models | BPMN-style models for application evaluation, monitoring, and final report evaluation. |
| [/docs/erasmus/final-report-llm-eu-ai-act](/docs/erasmus/final-report-llm-eu-ai-act.md) | Compliance Analysis | Final-report stages mapped to LLM-assist potential and EU AI Act constraints. |
| [/docs/longevity-coach/requirements](/docs/longevity-coach/requirements.md) | Requirements | Functional and non-functional requirements for the Longevity Mentor compliance assistant. |
| [/docs/longevity-coach/use_cases/longevity_mentor](/docs/longevity-coach/use_cases/longevity_mentor.md) | Use Case | Lifestyle, biological age, and health optimization coaching assistant running fully locally. |
| [/docs/longevity-coach/health-integration-architecture](/docs/longevity-coach/health-integration-architecture.md) | Architecture | System design for local Google Health/Fit data ingestion, openEHR mapping, and local storage. |
| [/docs/longevity-coach/bia-e2e-flow](/docs/longevity-coach/bia-e2e-flow.md) | Process Models | BPMN-style model of the BIA end-to-end test: mock retrieval, openEHR mapping, encrypted persistence, and anonymized nutrition advice. |
| [/installer/README](/installer/README.md) | Installation Guide | How the build, provision, boot, test, and deployment pipeline is implemented with nox in the repository root. |
| [/.agents/agent_instructions](/.agents/agent_instructions.md) | Agent Instructions | Role, context, and development guidelines for the developer AI assistant. |
| [/.agents/skills/claude-assistant/SKILL](/.agents/skills/claude-assistant/SKILL.md) | Skill | Use this skill to delegate complex coding tasks or queries to Claude (Anthropic). |
