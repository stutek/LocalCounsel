# Compliance Assistant Requirements

## 1. Project Overview
A local assistant designed to review documents and reports, check for compliance against specific frameworks, generate evaluation reports, and facilitate partner consultations.

## 2. Use Cases
Specific use cases and their detailed requirements are documented in the `use_cases/` folder:
- [Erasmus+ Contract Management](file:///home/simon/GoogleDrive/AIassitant/use_cases/erasmus_plus.md)

## 3. Functional Requirements
- **Document Review**: Ability to ingest, parse, and extract information from various document formats.
- **Compliance Checking**: Cross-reference extracted document contents against predefined compliance rules based on the active use case.
- **Report Generation**: Automatically generate comprehensive evaluation reports detailing compliance status, highlighted issues, and action items.
- **Partner Consultation**: Provide a workflow or interface to consult partners regarding findings, clarify ambiguities, or request missing documentation.

## 4. Non-Functional / Architectural Requirements
- **Pluggable Intelligence Engine**: The underlying Large Language Model (LLM) MUST be pluggable and easily replaceable. The default engine will be a **local Gemma 4 model**. The system architecture should not be tightly coupled to this model, allowing future swaps.
- **Incremental Development**: System architecture must be modular to support incremental feature additions over time.
- **Regression Testing**: The system must include a robust regression testing suite to ensure that compliance logic and document parsing remain stable across updates and model swaps.
- **GDPR Compliance & Data Privacy**: The solution must be fully GDPR compliant. This requires strict control over Personally Identifiable Information (PII) found in documents.
  - *Note on LLMs*: While GDPR does not strictly mandate a local LLM (enterprise cloud LLMs with Data Processing Agreements can be compliant), a **local LLM** is highly recommended as it guarantees that sensitive data never leaves the user's infrastructure, drastically simplifying compliance. Alternatively, a PII-scrubbing pipeline must be implemented before sending any data to a cloud LLM.
- **Security & Sandboxing**: The solution must be highly secure. The application must run under a dedicated, unprivileged user account to enforce strict filesystem access controls. Furthermore, it should execute within a `chroot` (change root) environment or container to fully sandbox the process and prevent any unauthorized access to the host operating system.
- **Rapid Demo Provisioning**: A demo environment must be able to start up in a few minutes using a single command. This implies automated provisioning (e.g., via a Makefile, bash setup script, or Docker Compose) that handles the creation of the sandbox, installation of dependencies, and initialization of the pluggable LLM without manual intervention.
