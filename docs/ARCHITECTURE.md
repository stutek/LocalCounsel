---
type: Architecture
title: Architecture — LocalCounsel
description: System design covering components, provisioning/startup flow, the compliance review workflow, and LLM pluggability.
tags: [architecture, design, llm, local-first]
timestamp: 2026-06-30T23:39:47+02:00
---

# Architecture — LocalCounsel

A local assistant for reviewing documents and checking compliance (e.g. Erasmus+).
The entire solution runs **locally** (GDPR), is **modular**, and uses a **pluggable LLM**.

## Table of contents

1. [Component overview](#1-component-overview)
2. [Provisioning & startup flow](#2-provisioning--startup-flow)
3. [Use case — compliance review workflow (BPMN-style)](#3-use-case--compliance-review-workflow-bpmn-style)
   - [3.1 Runtime interaction (sequence)](#31-runtime-interaction-sequence)
4. [Key architectural decisions](#4-key-architectural-decisions)
5. [LLM pluggability](#5-llm-pluggability)

## 1. Component overview

The solution consists of four layers: the automation pipeline (nox), the local
inference backend (llama.cpp + a pluggable GGUF model), the RAG/UI engine
(AnythingLLM), and the custom compliance business logic (Python / openai).

```mermaid
graph TB
    subgraph Host["🖥️ Local host (sandbox, unprivileged user)"]
        subgraph Pipeline["⚙️ nox pipeline — single source of truth"]
            PROV["provision<br/>(idempotent downloads)"]
            BOOT["bootLlm"]
            RUNT["run / test"]
            UIT["startAnythingLlm"]
        end

        subgraph Inference["🧠 Inference backend (pluggable)"]
            LS["llama-server<br/>127.0.0.1:8080<br/>OpenAI-compatible API"]
            GG["Gemma-2-2b-it<br/>(GGUF, quantized Q4_K_M)"]
            LS --- GG
        end

        subgraph App["📋 Compliance Assistant (custom logic)"]
            KT["Python app<br/>assistant.py"]
            L4J["openai client<br/>OpenAI(base_url=…)"]
            KT --- L4J
        end

        subgraph RAG["📚 RAG + UI engine (adopted)"]
            ALM["AnythingLLM Desktop<br/>documents, workspaces, chat UI"]
        end

        DOCS[("📄 Documents to review<br/>+ requirements / use cases")]
    end

    HF["☁️ HuggingFace<br/>(model weights)"]
    GH["☁️ GitHub releases<br/>(llama.cpp binaries)"]
    CDN["☁️ AnythingLLM CDN<br/>(AppImage)"]

    HF -. "download (once)" .-> PROV
    GH -. "download (once)" .-> PROV
    CDN -. "download (once)" .-> PROV

    PROV --> LS
    PROV --> ALM
    BOOT --> LS
    RUNT --> KT
    UIT --> ALM

    L4J -->|"HTTP /v1 (local)"| LS
    ALM -->|"HTTP /v1 (local)"| LS
    DOCS --> ALM
    DOCS --> KT

    classDef cloud fill:#e8eef7,stroke:#5b7aa8,color:#222;
    classDef local fill:#eef7ee,stroke:#5ba85b,color:#222;
    class HF,GH,CDN cloud;
    class LS,GG,KT,L4J,ALM,DOCS local;
```

## 2. Provisioning & startup flow

The demo environment starts with a single command via the nox pipeline.
Downloads are idempotent — they run identically everywhere and only when an
artifact does not yet exist.

```mermaid
flowchart TD
    START([nox -s run / ui]) --> P{provision}

    P --> DM["downloadModel<br/>Gemma GGUF"]
    P --> DL["downloadLlamaCpp"]
    P --> DA["downloadAnythingLLM"]

    DL --> EX["extractLlamaCpp<br/>(fix broken symlinks<br/>with safe fallback)"]
    DA --> CH["chmodAnythingLLM"]

    DM --> BL
    EX --> BL
    CH --> BL

    BL["bootLlm<br/>start llama-server"] --> WAIT{"wait for port 8080<br/>(up to 60s)"}
    WAIT -->|"OK"| READY["✅ LLM online<br/>save PID"]
    WAIT -->|"timeout"| FAIL["❌ kill process<br/>+ error"]

    READY --> APP["Python app / test<br/>or AnythingLLM UI"]

    STOP([nox -s stop_llm]) -.-> KILL["read PID<br/>kill process group + descendants<br/>clean up resources"]
```

## 3. Use case — compliance review workflow (BPMN-style)

This is how the solution is actually used (Erasmus+ example), modelled as a
BPMN-style process: swimlanes per participant, a start/end event (circles), an
exclusive gateway (diamond) for the compliance decision, and a loop back to
ingestion when partners must clarify or supply missing documents.

> Note: Mermaid has no native BPMN diagram type, so this approximates BPMN
> notation (lanes = subgraphs, events = circles, gateway = diamond). For
> standards-true BPMN, export this flow to a `.bpmn` file via a tool such as
> [BPMN Sketch Miner](https://www.bpmn-sketch-miner.ai).

```mermaid
flowchart LR
    classDef event fill:#d5f5d5,stroke:#3c873c,stroke-width:2px,color:#222;
    classDef endev fill:#f8d7da,stroke:#c0392b,stroke-width:2px,color:#222;
    classDef gw fill:#fff3cd,stroke:#d4a017,stroke-width:2px,color:#222;
    classDef task fill:#eaf2fb,stroke:#5b7aa8,color:#222;

    subgraph OFF["🧑 Compliance officer"]
        direction LR
        START((Start)):::event
        UPLOAD["Upload project<br/>documents"]:::task
        TRIGGER["Trigger<br/>compliance check"]:::task
        RECEIVE["Receive report<br/>& action items"]:::task
        ENDEV(((End))):::endev
    end

    subgraph RAGLANE["📚 AnythingLLM (RAG)"]
        direction LR
        PARSE["Parse, chunk<br/>& embed"]:::task
    end

    subgraph ASSIST["📋 Compliance Assistant"]
        direction LR
        RETRIEVE["Retrieve context<br/>& run rule checks"]:::task
        GW{"Compliant?"}:::gw
        REPORT["Generate<br/>evaluation report"]:::task
    end

    subgraph PARTNER["🤝 Partner"]
        direction LR
        CLARIFY["Provide clarifications<br/>/ missing docs"]:::task
    end

    START --> UPLOAD --> PARSE --> TRIGGER --> RETRIEVE --> GW
    GW -->|"Pass"| REPORT --> RECEIVE --> ENDEV
    GW -->|"Issues / missing info"| CLARIFY
    CLARIFY -->|"Updated docs"| PARSE
```

### 3.1 Runtime interaction (sequence)

How the components collaborate during a single compliance check.

```mermaid
sequenceDiagram
    actor Officer as Compliance officer
    participant UI as AnythingLLM (RAG + UI)
    participant App as Compliance Assistant<br/>(Python / openai)
    participant LLM as llama-server<br/>(Gemma, /v1)

    Officer->>UI: Upload project documents
    UI->>UI: Parse, chunk & embed (RAG)
    Officer->>App: Run compliance check (Erasmus+)
    App->>UI: Retrieve relevant document context
    UI-->>App: Top-k relevant chunks
    App->>LLM: Prompt: rules + context
    LLM-->>App: Findings (compliant / issues)
    alt Missing info or ambiguity
        App-->>Officer: Flag for partner consultation
        Officer->>UI: Add clarifications / documents
    end
    App->>LLM: Summarize findings
    LLM-->>App: Draft evaluation report
    App-->>Officer: Evaluation report + action items
```

## 4. Key architectural decisions

| Requirement | Decision (Build vs. Adopt) | Realization |
| --- | --- | --- |
| RAG + UI engine | **Adopt** — no custom chat UI | AnythingLLM Desktop |
| Intelligence engine (LLM) | **Adopt + pluggable** | llama.cpp + Gemma via OpenAI-compatible API |
| Compliance business logic | **Build** — custom integrations | Python + openai client |
| Automation / installation | **Build** — single source of truth | nox sessions (`provision`, `boot_llm`, `run`, `stop_llm`) |
| Privacy / GDPR | Everything runs locally | No data leaves host; sandbox, unprivileged user |

## 5. LLM pluggability

Both the custom Python app and the RAG engine access the model exclusively through
an **OpenAI-compatible HTTP interface** at `127.0.0.1:8080/v1`. The inference
backend or model can therefore be swapped (another GGUF, another server) without
changing any business logic — the interface stays the same.
