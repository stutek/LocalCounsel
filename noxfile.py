"""LocalCounsel automation pipeline (nox).

It provisions the local LLM stack (model weights + llama.cpp + AnythingLLM),
boots/stops the inference server, and runs the app and tests. All ops logic lives
here; the application code stays clean under ``src/``.

Common sessions:
    nox -s provision   # idempotently download + extract everything
    nox -s boot_llm    # start llama-server and wait for it to be ready
    nox -s run         # boot the LLM (if needed) and run the assistant
    nox -s test        # boot the LLM (if needed) and run pytest
    nox -s stop_llm    # stop the server and its child processes
    nox -s ui          # launch the AnythingLLM desktop UI

The model is pluggable: override LC_MODEL_URL / LC_MODEL_NAME (and optionally
LC_LLAMA_URL) to run a different GGUF — e.g. DeepSeek instead of Gemma — with no
code changes.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path

import nox

# --------------------------------------------------------------------------- #
# Paths & configuration (env-overridable)                                      #
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).parent
BUILD = ROOT / "build"            # gitignored; reused as a download/work cache
DOWNLOADS = BUILD / "downloads"
LLAMA_DIR = BUILD / "llama_cpp"
PID_FILE = BUILD / "llama.pid"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


MODEL_URL = _env(
    "LC_MODEL_URL",
    "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q4_K_M.gguf",
)
MODEL_FILE = DOWNLOADS / _env("LC_MODEL_FILE", MODEL_URL.rsplit("/", 1)[-1])

LLAMA_URL = _env(
    "LC_LLAMA_URL",
    "https://github.com/ggml-org/llama.cpp/releases/download/b9487/llama-b9487-bin-ubuntu-x64.tar.gz",
)
LLAMA_TAR = DOWNLOADS / "llama.tar.gz"

ANYTHINGLLM_URL = _env(
    "LC_ANYTHINGLLM_URL",
    "https://cdn.anythingllm.com/latest/AnythingLLMDesktop.AppImage",
)
ANYTHINGLLM_APP = DOWNLOADS / "AnythingLLMDesktop.AppImage"

HOST = _env("LC_LLM_HOST", "127.0.0.1")
PORT = int(_env("LC_LLM_PORT", "8080"))

nox.options.sessions = ["test"]
nox.options.reuse_existing_virtualenvs = True


# --------------------------------------------------------------------------- #
# Provisioning helpers                                                         #
# --------------------------------------------------------------------------- #
def _download(url: str, dest: Path) -> None:
    """Idempotently stream a URL to ``dest`` (skips if already present)."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"✓ {dest.name} already present")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"↓ downloading {url}\n    → {dest}")
    req = urllib.request.Request(url, headers={"User-Agent": "local-counsel/0.1"})
    with urllib.request.urlopen(req) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            read += len(chunk)
            if total:
                pct = read * 100 // total
                print(f"\r    {pct:3d}%  ({read >> 20} / {total >> 20} MiB)", end="", flush=True)
        if total:
            print()
    tmp.replace(dest)


def _extract_llama() -> None:
    """Extract the llama.cpp tarball.

    Python's tarfile preserves symlinks natively, so no manual symlink repair is
    needed after extraction.
    """
    server = _find_server()
    if server is not None:
        print("✓ llama.cpp already extracted")
        return
    LLAMA_DIR.mkdir(parents=True, exist_ok=True)
    print("⇲ extracting llama.cpp ...")
    with tarfile.open(LLAMA_TAR, "r:gz") as tar:
        try:
            tar.extractall(LLAMA_DIR, filter="data")  # py3.12+ safe filter
        except TypeError:
            tar.extractall(LLAMA_DIR)


def _find_server() -> Path | None:
    if not LLAMA_DIR.exists():
        return None
    for name in ("llama-server", "server"):
        for path in LLAMA_DIR.rglob(name):
            if path.is_file():
                return path
    return None


def _provision() -> None:
    _download(MODEL_URL, MODEL_FILE)
    _download(LLAMA_URL, LLAMA_TAR)
    _extract_llama()
    _download(ANYTHINGLLM_URL, ANYTHINGLLM_APP)
    ANYTHINGLLM_APP.chmod(0o755)


# --------------------------------------------------------------------------- #
# Server lifecycle helpers                                                     #
# --------------------------------------------------------------------------- #
def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _boot_llm() -> None:
    """Start llama-server (if not already up) and wait for it to bind the port."""
    if _port_open(HOST, PORT):
        print(f"✓ LLM already serving on {HOST}:{PORT}")
        return

    _provision()
    server = _find_server()
    if server is None:
        raise SystemExit("llama-server binary not found after provisioning!")
    server.chmod(0o755)

    print("Starting llama-server ...")
    env = {**os.environ, "LD_LIBRARY_PATH": str(server.parent)}
    proc = subprocess.Popen(
        [str(server), "-m", str(MODEL_FILE), "--host", HOST, "--port", str(PORT)],
        cwd=str(server.parent),
        env=env,
        start_new_session=True,  # own process group → clean group-kill in stop_llm
    )
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(proc.pid))

    print(f"Waiting for LLM server to bind to {HOST}:{PORT} ", end="", flush=True)
    for _ in range(60):
        if _port_open(HOST, PORT):
            print("\n✅ LLM server is online!")
            return
        if proc.poll() is not None:
            raise SystemExit(f"llama-server exited early (code {proc.returncode}).")
        print(".", end="", flush=True)
        time.sleep(1)

    proc.terminate()
    raise SystemExit(f"\nLLM server failed to start on {HOST}:{PORT}.")


def _stop_llm() -> None:
    if not PID_FILE.exists():
        print("No active LLM server PID file found.")
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        pgid = os.getpgid(pid)
        print(f"🛑 Stopping LLM server (PID {pid}) and child processes ...")
        os.killpg(pgid, signal.SIGTERM)
        for _ in range(10):
            if not _pid_alive(pid):
                break
            time.sleep(0.5)
        if _pid_alive(pid):
            os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        print(f"LLM server (PID {pid}) is no longer running.")
    finally:
        PID_FILE.unlink(missing_ok=True)
        print("🧹 Resources cleaned up.")


# --------------------------------------------------------------------------- #
# Sessions                                                                     #
# --------------------------------------------------------------------------- #
@nox.session(python=False)
def provision(session: nox.Session) -> None:
    """Idempotently download + extract all models and binaries."""
    _provision()


@nox.session(python=False)
def boot_llm(session: nox.Session) -> None:
    """Boot the LLM server and wait until it is ready."""
    _boot_llm()


@nox.session(python=False)
def stop_llm(session: nox.Session) -> None:
    """Stop the LLM server (and its children) and clean up."""
    _stop_llm()


@nox.session
def run(session: nox.Session) -> None:
    """Boot the LLM (if needed) and run the assistant."""
    session.install("-e", ".")
    _boot_llm()
    session.run("python", "-m", "local_counsel.assistant")


@nox.session
def test(session: nox.Session) -> None:
    """Boot the LLM (if needed) and run the integration tests."""
    session.install("-e", ".[test]")
    _boot_llm()
    session.run("pytest")


@nox.session(python=False)
def ui(session: nox.Session) -> None:
    """Launch the AnythingLLM desktop UI (boots the LLM first)."""
    _boot_llm()
    print("Booting AnythingLLM UI ...")
    subprocess.run([str(ANYTHINGLLM_APP), "--appimage-extract-and-run"], check=False)
