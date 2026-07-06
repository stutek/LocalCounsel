---
type: Requirements
title: Erasmus+ Compliance Assistant Requirements
description: Functional and non-functional requirements for the Erasmus+ project compliance assistant.
tags: [requirements, compliance, erasmus-plus]
timestamp: 2026-07-06T13:38:00+02:00
---

# Erasmus+ Compliance Assistant Requirements

## 1. Project Overview
A local assistant designed to review documents and reports, check for compliance against specific Erasmus+ regulatory frameworks, generate evaluation reports, and facilitate partner consultations.

The assistant is built to **support contract managers (*skrbniki pogodbe*) and financial controllers (*finančni nadzorniki*)** in the supported processes (application evaluation, project monitoring, and final report evaluation). These processes are modelled as BPMN-style diagrams in [docs/erasmus-processes.md](../../docs/erasmus-processes.md).

## 2. Use Cases
- [Erasmus+ Contract Management](use_cases/erasmus_plus.md)

## 3. Functional Requirements
- **Document Review**: Ability to ingest, parse, and extract information from Erasmus+ applications, interim monitoring sheets, and final reports.
- **Compliance Checking**: Cross-reference extracted document contents against predefined compliance rules based on the active use case.
- **Report Generation**: Automatically generate comprehensive evaluation reports detailing compliance status, highlighted issues, and action items.
- **Partner Consultation**: Provide a workflow or interface to consult partners regarding findings, clarify ambiguities, or request missing documentation.
