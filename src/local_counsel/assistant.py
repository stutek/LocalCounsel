"""LocalCounsel application entry point.

Connects to the local OpenAI-compatible LLM server (llama.cpp + a pluggable GGUF
model, provisioned and booted by the nox pipeline) and runs a readiness ping.
The model behind the API is interchangeable — see ``config.py``.
"""

from __future__ import annotations

from openai import OpenAI

from .config import Settings, load_settings

PING_PROMPT = (
    "Hello! Please introduce yourself, identify your core model architecture "
    "(e.g., Gemma, DeepSeek, Llama), and confirm you are ready to review "
    "compliance documents."
)


def build_client(settings: Settings | None = None) -> OpenAI:
    """Build an OpenAI client pointed at the local server."""
    settings = settings or load_settings()
    return OpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key,
        timeout=settings.timeout_s,
    )


def ask(prompt: str, settings: Settings | None = None, client: OpenAI | None = None) -> str:
    """Send a single chat prompt and return the model's reply text."""
    settings = settings or load_settings()
    client = client or build_client(settings)
    response = client.chat.completions.create(
        model=settings.model_name,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def main() -> None:
    settings = load_settings()
    print("==================================================")
    print("LocalCounsel initialized (Python / openai)")
    print(f"Endpoint: {settings.base_url}  ·  model: {settings.model_name}")
    print("==================================================")

    print("\nSystem ready to accept document parsing and compliance checks!")
    print("Sending test ping to local LLM...")
    reply = ask(PING_PROMPT, settings)
    print(f"\nModel Response: {reply}")


if __name__ == "__main__":
    main()
