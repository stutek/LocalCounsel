---
type: Use Case
title: "Use Case: Longevity Mentor"
description: Lifestyle, biological age, and health optimization coaching assistant running fully locally for GDPR and privacy compliance.
tags: [use-case, longevity, health, requirements]
timestamp: 2026-07-08T13:36:00+02:00
---

# Use Case: Longevity Mentor

## 1. Scope
Coaching, lifestyle recommendations, biological age tracking, and compliance checking for healthy longevity optimization. The assistant analyzes user-provided health records, blood panel details, sleep stats, and daily routines, comparing them against established health metrics and longevity science guidelines (e.g. cardiovascular health, glycemic control, sleep architecture).

Processing runs locally by default (GDPR / medical privacy), and raw, identifiable health data is never uploaded to third-party cloud services. For advanced reasoning, this use case may optionally send **anonymized, PII-scrubbed** metrics (see §6.3 of the [health integration architecture](../../../docs/health-integration-architecture.md)) to an external frontier model; this hybrid path is disabled in air-gapped mode.

## 1a. Supported Users (Personas)
- **Longevity Coach / Mentor**: Analyzes client records, generates personalized exercise/sleep/nutrition plans, and tracks changes over time.
- **Privacy-Conscious Individual**: Interacts directly with the local model to receive health insights and cross-check routine choices without leaking private medical logs.

## 2. Goals
- Review blood test panels, biometric logs, and routine journals.
- Securely fetch and synchronize Google Health / Google Fit records into a locally-hosted openEHR database instance.
- Utilize OKF (Open Knowledge Format) Markdown files to document and index the user's specific longevity goals, past/current lifestyle experiments, optimization parameters, and prioritized intervention roadmaps.
- Provide science-backed recommendations for exercise (zone 2, VO2 max), diet (glycemic index, nutrient density), sleep, and stress management.
- Highlight metrics that fall outside standard clinical reference bounds or optimal longevity target zones.

## 3. Specific Compliance & Safety Checks
- Verify health guidelines: Cross-reference recommendations with safe athletic/metabolic guidelines.
- openEHR Schema Integrity: Ensure ingested Google Health data formats map correctly to openEHR templates and archetypes without loss of clinical context.
- Privacy & Anonymization Constraints: The local anonymization layer must completely strip all PII before sending data to external APIs. To prevent age-matching re-identification, the subject's exact age must be dynamically anonymized with a +/- 15% fuzzing offset before transmission.
- Flag high-risk suggestions: Explicitly require human medical review for any warnings related to medications, chronic conditions, or extreme supplementation.
- Mark all output clearly as "AI-generated educational guidance, not medical advice" (EU AI Act transparency and medical liability safeguards).

## 4. Intervention Hierarchy & Coaching Behavior
- **Intervention Hierarchy**: Prioritize building sustainable, long-term habits (sleep hygiene, daily movement, circadian alignment) over therapeutic interventions. First adjust nutrition, daily routines, and lifestyle factors before recommending medications, clinical treatments, procedures, or medical interventions.
- **Coaching Persona & Tone**: The mentor must be patient and anticipate that human behavioral change is non-linear, expecting periods of regression. It should act as a compassionate, encouraging, and empathetic accountability partner rather than an authoritarian clinical auditor.


