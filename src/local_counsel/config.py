"""Runtime configuration for the LocalCounsel app.

Everything is environment-overridable so the underlying model is *pluggable*:
the app talks to a local OpenAI-compatible server (llama.cpp's ``llama-server``),
so swapping Gemma for DeepSeek or any other GGUF is a config change, not a code
change. Point ``LC_MODEL_URL`` / ``LC_MODEL_NAME`` at a different model and reboot
the server — the client below is unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    model_name: str
    api_key: str
    timeout_s: float

    @property
    def base_url(self) -> str:
        # llama-server exposes an OpenAI-compatible API under /v1
        return f"http://{self.host}:{self.port}/v1"


def load_settings() -> Settings:
    """Read settings from the environment, with local-sandbox defaults."""
    return Settings(
        host=os.getenv("LC_LLM_HOST", "127.0.0.1"),
        port=int(os.getenv("LC_LLM_PORT", "8080")),
        # Logical name passed to the OpenAI-compatible API. The actual weights are
        # whatever GGUF the server was booted with (see noxfile LC_MODEL_URL).
        model_name=os.getenv("LC_MODEL_NAME", "gemma"),
        api_key=os.getenv("LC_LLM_API_KEY", "local"),  # ignored by the local server
        timeout_s=float(os.getenv("LC_LLM_TIMEOUT", "300")),
    )
