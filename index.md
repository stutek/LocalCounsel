# LocalCounsel — OKF Knowledge Bundle

This repository is an [Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
v0.1 bundle: every non-reserved Markdown file is an OKF *concept* carrying YAML
frontmatter with a required `type` field. A concept's ID is its file path with the
`.md` suffix removed.

## Concepts

| Concept ID | Type | Description |
| --- | --- | --- |
| [/README](/README.md) | Project Overview | Local-first compliance assistant that reviews documents against Erasmus+, GDPR, and EU AI Act using a pluggable local LLM. |
| [/requirements/requirements](/requirements/requirements.md) | Requirements | Functional and non-functional requirements for the assistant. |
| [/requirements/use_cases/erasmus_plus](/requirements/use_cases/erasmus_plus.md) | Use Case | Contract and execution management use case for Erasmus+ projects. |
| [/docs/ARCHITECTURE](/docs/ARCHITECTURE.md) | Architecture | System design: components, startup flow, review workflow, LLM pluggability. |
| [/docs/erasmus-processes](/docs/erasmus-processes.md) | Process Models | BPMN-style models for application evaluation, monitoring, and final report evaluation. |
| [/docs/final-report-llm-eu-ai-act](/docs/final-report-llm-eu-ai-act.md) | Compliance Analysis | Final-report stages mapped to LLM-assist potential and EU AI Act constraints. |
| [/installer/README](/installer/README.md) | Installation Guide | Automated build, test, and deployment pipeline. |
| [/.agents/agent_instructions](/.agents/agent_instructions.md) | Agent Instructions | Role, context, and development guidelines for the developer AI assistant. |
| [/.agents/skills/claude-assistant/SKILL](/.agents/skills/claude-assistant/SKILL.md) | Skill | Use this skill to delegate complex coding tasks or queries to Claude (Anthropic). |
