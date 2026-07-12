"""Paths and env-overridable configuration for the LocalCounsel pipeline.

Everything here is import-time constant material: repository paths, artifact
URLs, pinned SHA-256 digests, and the platform guard. No side effects.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths                                                                         #
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent  # repository root (pipeline/'s parent)
BUILD = ROOT / "build"            # gitignored; reused as a download/work cache
DOWNLOADS = BUILD / "downloads"
LLAMA_DIR = BUILD / "llama_cpp"
DIFY_DIR = BUILD / "dify"
PID_FILE = BUILD / "llama.pid"
REPORTS = BUILD / "reports"   # JUnit XML + Markdown test reports
LOGS = BUILD / "logs"         # llama-server + pytest run logs


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# --------------------------------------------------------------------------- #
# Platform defaults                                                             #
# --------------------------------------------------------------------------- #
# The Linux-x64 llama.cpp release is the primary supported target; its digest is
# pinned below (LLAMA_SHA256). macOS builds are best-effort and unpinned. Windows
# is not supported — see require_supported_platform().
LLAMA_LINUX_X64_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b9487/llama-b9487-bin-ubuntu-x64.tar.gz"


def get_llama_defaults() -> tuple[str, str]:
    sys_name = platform.system().lower()
    mach_name = platform.machine().lower()
    if sys_name == "darwin":
        if "arm" in mach_name:
            return "https://github.com/ggml-org/llama.cpp/releases/download/b9487/llama-b9487-bin-macos-arm64.tar.gz", "llama.tar.gz"
        return "https://github.com/ggml-org/llama.cpp/releases/download/b9487/llama-b9487-bin-macos-x64.tar.gz", "llama.tar.gz"
    if sys_name == "linux" and not ("x86_64" in mach_name or "amd64" in mach_name):
        return "https://github.com/ggml-org/llama.cpp/releases/download/b9487/llama-b9487-bin-ubuntu-arm64.tar.gz", "llama.tar.gz"
    # Default / Linux-x64 (primary supported target).
    return LLAMA_LINUX_X64_URL, "llama.tar.gz"


def get_anythingllm_defaults() -> tuple[str, str]:
    if platform.system().lower() == "darwin":
        return (
            "https://github.com/Mintplex-Labs/anything-llm/releases/download/v1.15.0/AnythingLLMDesktop.dmg",
            "AnythingLLMDesktop.dmg",
        )
    return (
        "https://github.com/Mintplex-Labs/anything-llm/releases/download/v1.15.0/AnythingLLMDesktop.AppImage",
        "AnythingLLMDesktop.AppImage",
    )


def get_dify_defaults() -> tuple[str, str]:
    return "https://github.com/langgenius/dify/archive/refs/tags/1.15.0.tar.gz", "dify.tar.gz"


_llama_url_default, _llama_name_default = get_llama_defaults()
_allm_url_default, _allm_name_default = get_anythingllm_defaults()
_dify_url_default, _dify_name_default = get_dify_defaults()

# --------------------------------------------------------------------------- #
# Artifacts (env-overridable)                                                   #
# --------------------------------------------------------------------------- #
MODEL_URL_DEFAULT = (
    "https://huggingface.co/bartowski/google_gemma-4-E2B-it-GGUF/resolve/b5e99bd964eaacc27ba484bb2eb3e9f6160b9143/google_gemma-4-E2B-it-Q4_K_M.gguf"
)
MODEL_URL = env("LC_MODEL_URL", MODEL_URL_DEFAULT)
MODEL_FILE = DOWNLOADS / env("LC_MODEL_FILE", MODEL_URL.rsplit("/", 1)[-1])

LLAMA_URL = env("LC_LLAMA_URL", _llama_url_default)
LLAMA_TAR = DOWNLOADS / env("LC_LLAMA_FILE", _llama_name_default)

ANYTHINGLLM_URL = env("LC_ANYTHINGLLM_URL", _allm_url_default)
ANYTHINGLLM_APP = DOWNLOADS / env("LC_ANYTHINGLLM_FILE", _allm_name_default)

DIFY_URL = env("LC_DIFY_URL", _dify_url_default)
DIFY_TAR = DOWNLOADS / env("LC_DIFY_FILE", _dify_name_default)

# --------------------------------------------------------------------------- #
# Download integrity (SHA-256)                                                  #
# --------------------------------------------------------------------------- #
# Idempotency rule: a download is only trustworthy if the bytes match a known-good
# digest. These digests were computed from the verified default artifacts and are
# env-overridable. They are ONLY valid for the exact default URL/platform — a
# custom LC_MODEL_URL or a non-Linux-x64 llama build has an unknown hash, so we
# leave it blank there and provisioning.download() falls back to a loud
# no-verification warning instead of failing on a guaranteed mismatch.
_MODEL_SHA256_DEFAULT = (
    "b5310340b3a23d31655d7119d100d5df1b2d8ee17b3ca8b0a23ad7e9eb5fa705"
    if MODEL_URL == MODEL_URL_DEFAULT
    else ""
)
_LLAMA_SHA256_DEFAULT = (
    "4ac97aee00335f3c5db1bd2d6178d6e655750a039bc9dd20bd4432dd17cc549f"
    if LLAMA_URL == LLAMA_LINUX_X64_URL
    else ""
)
_DIFY_SHA256_DEFAULT = (
    "18c9a711ac715855bd3d0882966b14143692a48269181c1dd7f7bfcc702a66ba"
    if DIFY_URL == "https://github.com/langgenius/dify/archive/refs/tags/1.15.0.tar.gz"
    else ""
)
MODEL_SHA256 = env("LC_MODEL_SHA256", _MODEL_SHA256_DEFAULT) or None
LLAMA_SHA256 = env("LC_LLAMA_SHA256", _LLAMA_SHA256_DEFAULT) or None
ANYTHINGLLM_SHA256 = env("LC_ANYTHINGLLM_SHA256", "") or None
DIFY_SHA256 = env("LC_DIFY_SHA256", _DIFY_SHA256_DEFAULT) or None

# --------------------------------------------------------------------------- #
# Server bind address                                                           #
# --------------------------------------------------------------------------- #
def _default_llm_host() -> str:
    """Choose a secure bind address for llama-server.

    Uses LC_LLM_HOST if explicitly configured. Otherwise:
    - If Docker bridge interface (docker0) is active, bind to its private bridge
      gateway IP (e.g., 172.17.0.1) so Dify containers can reach the host model
      without exposing port 8080 to physical LAN/Wi-Fi interfaces.
    - Otherwise, bind strictly to loopback 127.0.0.1.
    """
    override = env("LC_LLM_HOST", "")
    if override:
        return override
    try:
        out = subprocess.check_output(
            ["ip", "-4", "addr", "show", "docker0"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ip = line.split()[1].split("/")[0]
                if ip:
                    return ip
    except Exception:
        pass
    return "127.0.0.1"


HOST = _default_llm_host()
PORT = int(env("LC_LLM_PORT", "8080"))


def require_supported_platform() -> None:
    """Guard the server/app sessions: Windows is not yet supported.

    Windows support is only half-wired (e.g. the ``test`` session shells out to
    bash with ``set -o pipefail``), so rather than fail deep inside a session we
    stop early with a clear message. Kept as a helper (not a module-level check)
    so importing the pipeline and the platform-agnostic ``okf``/``unit`` sessions
    stay usable everywhere.
    """
    if platform.system().lower() == "windows":
        raise SystemExit(
            "Windows is not yet supported — Linux x64 is the primary target, "
            "macOS is best-effort. Run under Linux (or WSL) instead."
        )
