# LocalCounsel

A **local-first compliance assistant** that reviews documents and reports against
regulatory frameworks (Erasmus+, GDPR, EU AI Act), generates evaluation reports,
and supports partner consultations — all running **entirely on your own machine**
so sensitive data never leaves your infrastructure.

The LLM is **pluggable**: the app talks to a local OpenAI-compatible
`llama-server`, so the underlying model (Gemma, DeepSeek, …) is swapped by
booting a different GGUF — no code changes.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design and
[requirements/requirements.md](requirements/requirements.md) for requirements.

## Stack

| Layer | Choice |
| --- | --- |
| Automation pipeline | **nox** (`noxfile.py`) |
| Inference backend | **llama.cpp** + a pluggable GGUF model |
| RAG + UI engine | **AnythingLLM** Desktop |
| Compliance logic | **Python** + the `openai` client |

## Requirements

- Python 3.10+
- [`nox`](https://nox.thea.codes/) — `pipx install nox` (or `pip install nox`)
- Linux x64 (the pinned llama.cpp binary and AnythingLLM AppImage target Ubuntu x64)

## Usage

```bash
nox -s provision   # idempotently download model + llama.cpp + AnythingLLM
nox -s boot_llm    # start llama-server and wait until it is ready
nox -s run         # boot the LLM (if needed) and run the assistant
nox -s test        # boot the LLM (if needed) and run the integration tests
nox -s stop_llm    # stop the server and its child processes
nox -s ui          # launch the AnythingLLM desktop UI
```

The first `provision`/`boot_llm` downloads several GB (model weights + binaries)
into `build/` (gitignored). Subsequent runs reuse the cache.

## Configuration

All settings are environment-overridable. To run a **different model**, point the
pipeline at another GGUF and update the logical model name:

| Variable | Default | Purpose |
| --- | --- | --- |
| `LC_MODEL_URL` | Gemma-2-2b-it Q4_K_M GGUF | Model weights to download |
| `LC_MODEL_NAME` | `gemma` | Logical name sent to the API |
| `LC_LLAMA_URL` | pinned llama.cpp release | Inference backend binaries |
| `LC_LLM_HOST` / `LC_LLM_PORT` | `127.0.0.1` / `8080` | Server bind address |
| `LC_LLM_TIMEOUT` | `300` | Client timeout (seconds) |

Example — run a different model:

```bash
LC_MODEL_URL="https://…/some-model.gguf" LC_MODEL_NAME="deepseek" nox -s run
```

## Compliance posture

The LLM is used strictly as **decision-support with a human in the loop** on every
gateway and final decision, keeping the system out of the EU AI Act high-risk
category. Running fully locally keeps processing GDPR-friendly. Final
classification for any concrete deployment requires legal/DPO review — see
[docs/final-report-llm-eu-ai-act.md](docs/final-report-llm-eu-ai-act.md).
