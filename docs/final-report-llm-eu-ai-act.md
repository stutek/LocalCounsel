---
type: Compliance Analysis
title: Final report evaluation — LLM-assist potential & EU AI Act constraints
description: Maps final-report-evaluation stages to LLM-assist potential and the EU AI Act constraints and safeguards that apply.
tags: [eu-ai-act, compliance, llm, erasmus-plus]
timestamp: 2026-06-30T23:23:37+02:00
---

# Final report evaluation — LLM-assist potential & EU AI Act constraints

Maps each stage of the [final report evaluation process](erasmus-processes.md#3-final-report-evaluation)
to where a **small local LLM** (e.g. gemma-2-2b / a small "Gemma") can help, together
with the **EU AI Act** constraints and safeguards that apply.

> ⚠️ **Not legal advice.** This is an engineering risk-mapping to guide design. The
> final classification of the system under the EU AI Act must be confirmed with
> legal/DPO review for the concrete deployment.

Assist legend: ✅ LLM draft is a good fit · 🟡 LLM assists, human decides · ❌ keep human / deterministic code (no LLM).

## 1. Per-stage mapping

| Stage (node) | Lane | LLM assist | How the LLM helps | EU AI Act constraint / safeguard |
|---|---|---|---|---|
| **Check report completeness** (`COMPLETE`) | Contract manager | ✅ | Checklist against a template: are all required sections/fields present. | Low intrinsic risk. Mark output as AI-generated (Art. 50(2)); human verifies; log the run (record-keeping). |
| **Request missing info** (`REQUEST`) | Contract manager | ✅ | Draft the request letter/email listing missing items. | Art. 50(2) mark as AI-assisted; Art. 50(4) the officer holds **editorial responsibility** before sending (exemption basis). |
| **Verify & validate project data** (`VALIDATE`) | Contract manager | 🟡 | Cross-check narrative vs. structured data; flag inconsistencies. | Authoritative validation stays **deterministic**; LLM only flags. Keep logs; ensure accuracy (no silent errors). |
| **Assess content quality** (`CONTENT`) | Content assessor | 🟡 (draft) | First-pass qualitative assessment vs. award/quality criteria via RAG; extract evidence, highlight gaps. | Human oversight (Art. 14 principle); **human assigns the score**. Require **source citations** (accuracy/robustness). Must not evaluate a *natural person's* learning outcomes → would trigger Annex III(3). |
| **Quality score ≥ threshold?** (`GQUAL`) | Content assessor | ❌ | (LLM may only suggest.) | Decision step → **human**. Avoid solely-automated decision (GDPR Art. 22); keeps system out of high-risk. |
| **Verify eligible costs & budget categories** (`FINANCE`) | Financial controller | 🟡 | Classify costs into budget categories; check against eligibility-rule text; extract figures; flag suspicious items. | **No arithmetic via LLM** — totals by deterministic code. Must **not** score creditworthiness of persons (Annex III(5)(b)). Advisory only. |
| **Events implemented & costs eligible?** (`GIMPL`) | Financial controller | ❌ | (LLM may only suggest.) | Financial decision → **human + deterministic calc**. Automating effects on a natural-person beneficiary risks Annex III(5)(a) high-risk + GDPR Art. 22. |
| **Reduce grant / Recover undue amounts** (`REDUCE` / `RECOVER`) | — | ❌ | Not an LLM task. | Monetary/legal effect ("reduce/reclaim") — **never automated**. Human decision + auditable calculation. |
| **Send written feedback** (`FEEDBACK`) | Contract manager | ✅ | Draft written feedback summarising both reviews' findings. | Art. 50(2) mark AI-generated; Art. 50(4) human editorial responsibility before issuing. |
| **Consolidate & determine final payment** (`DECIDE`) / **Authorise payment/recovery** (`AUTH`) | Authorising Officer | ❌ | Not an LLM task. | Authoritative decision/authorisation → **human**. Full traceability and logging. |

## 2. Likely regulatory classification

In the **intended configuration** — decision-support only, human-in-the-loop on
every gateway (`GQUAL`, `GIMPL`) and on `DECIDE`/`AUTH` — the system most likely
falls under **limited-risk transparency obligations (Art. 50)** rather than
high-risk, because it:

- assesses an **organisation's project report**, not a *natural person's* learning
  outcomes or admission (so outside **Annex III(3) — education**);
- does **not** determine eligibility of *natural persons* for **essential public
  assistance benefits/services** (so outside **Annex III(5)(a)**); Erasmus+ grants
  are project funding, typically to organisations;
- does **not** score creditworthiness (outside **Annex III(5)(b)**).

**It would become high-risk** (triggering Arts. 9–15: risk management, data
governance, technical documentation, logging, transparency, human oversight,
accuracy/robustness/cybersecurity, plus conformity assessment) if it were used to
**automatically make or decisively influence** grant award / reduction / recovery
decisions affecting **natural-person** beneficiaries, or to evaluate individuals'
learning outcomes. The mitigation is structural: **keep the LLM advisory**.

## 3. Cross-cutting obligations & safeguards

- **Transparency (Art. 50, applies 2 Aug 2026):** all AI-generated text (drafts,
  feedback letters) must carry **machine-readable marking** and be disclosed as
  AI-generated. Systems already in use get until **2 Dec 2026** for the marking.
- **Human editorial responsibility (Art. 50(4)):** every outward document is
  reviewed and owned by a human officer before issuing.
- **GPAI model (Art. 53):** Gemma is a general-purpose AI model — provider duties
  (documentation, copyright policy) sit with the **model provider**; the deployer
  should respect the model's acceptable-use and keep transparency.
- **No prohibited practices (Art. 5):** no social scoring, biometric categorisation,
  emotion recognition, etc. (not used here).
- **GDPR overlap:** Art. 22 (no solely automated decisions with legal/significant
  effect) and data minimisation. The **fully local** architecture (no data leaves
  the host) directly supports this and the project's GDPR requirement.
- **Accuracy for a small model:** require **source citations** for every finding,
  route arithmetic to deterministic code, use RAG (don't load whole reports), and
  treat all outputs as drafts subject to human review.

## 4. Sources

- [EU AI Act — Annex III: High-Risk AI Systems](https://artificialintelligenceact.eu/annex/3/)
- [EU AI Act — Article 50: Transparency obligations](https://artificialintelligenceact.eu/article/50/)
- [Article 50 transparency rules — practical guide](https://artificialintelligenceact.eu/transparency-rules-article-50/)
- [AI Act Service Desk (European Commission) — Annex III](https://ai-act-service-desk.ec.europa.eu/en/ai-act/annex-3)
- [AI Act Service Desk (European Commission) — Article 50](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-50)
- [Shaping Europe's digital future — AI Act regulatory framework](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)
