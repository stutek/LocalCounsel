"""llama-server lifecycle: health polling, boot, and shutdown."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .config import HOST, LOGS, MODEL_FILE, PID_FILE, PORT, require_supported_platform
from .provisioning import find_dify, find_server, provision
from .util import link_latest, stamp


def health_ok(host: str, port: int) -> bool:
    """True only once llama-server is fully ready.

    The server binds the port *before* the model finishes loading, answering
    /health with 503 ("Loading model") until ready and 200 afterwards. Polling the
    TCP port alone races the model load, so we check /health instead.
    """
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def tail(path: Path, n: int = 25) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return "(no log)"


def boot_llm(log_stamp: str | None = None) -> None:
    """Start llama-server (if not already up) and wait for it to bind the port.

    The server is detached (own process group) and outlives this nox process, so
    its stdout/stderr are redirected to a persistent, timestamped log file under
    build/logs/ — tail it live with ``tail -f build/logs/llama-latest.log``.
    """
    require_supported_platform()
    if health_ok(HOST, PORT):
        print(f"✓ LLM already serving on {HOST}:{PORT}")
        return

    provision()
    server = find_server()
    if server is None:
        raise SystemExit("llama-server binary not found after provisioning!")
    try:
        server.chmod(0o755)
    except OSError:
        pass

    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"llama-{log_stamp or stamp(datetime.now(timezone.utc))}.log"
    logf = open(log_path, "w")  # noqa: SIM115 — kept open for the detached server's lifetime
    link_latest(log_path, LOGS / "llama-latest.log")

    print(f"Starting llama-server ... (logging to {log_path})")
    env = {**os.environ, "LD_LIBRARY_PATH": str(server.parent)}

    proc = subprocess.Popen(
        [str(server), "-m", str(MODEL_FILE), "--host", HOST, "--port", str(PORT)],
        cwd=str(server.parent),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # detach into its own process group (POSIX)
    )
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(proc.pid))

    print(f"Waiting for LLM server on {HOST}:{PORT} to load the model ", end="", flush=True)
    for _ in range(180):  # model load can take a while for larger GGUFs
        if health_ok(HOST, PORT):
            print("\n✅ LLM server is online!")
            return
        if proc.poll() is not None:
            raise SystemExit(
                f"llama-server exited early (code {proc.returncode}). Last log lines:\n{tail(log_path)}"
            )
        print(".", end="", flush=True)
        time.sleep(1)

    proc.terminate()
    raise SystemExit(
        f"\nLLM server failed to start on {HOST}:{PORT}. Last log lines:\n{tail(log_path)}"
    )


def stop_llm() -> None:
    require_supported_platform()
    if not PID_FILE.exists():
        print("No active LLM server PID file found.")
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        pgid = os.getpgid(pid)
        print(f"🛑 Stopping LLM server (PID {pid}) and child processes ...")
        os.killpg(pgid, signal.SIGTERM)

        for _ in range(10):
            if not pid_alive(pid):
                break
            time.sleep(0.5)

        if pid_alive(pid):
            os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        print(f"LLM server (PID {pid}) is no longer running.")
    finally:
        PID_FILE.unlink(missing_ok=True)
        print("🧹 Resources cleaned up.")


def _docker_compose_cmd() -> list[str] | None:
    if shutil.which("docker") and subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0:
        return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return None


def boot_dify(log_stamp: str | None = None) -> None:
    """Boot Dify stack via Docker Compose (boots local LLM first if needed)."""
    require_supported_platform()
    boot_llm(log_stamp=log_stamp)

    provision()
    docker_dir = find_dify()
    if docker_dir is None:
        raise SystemExit("Dify docker directory not found after provisioning!")

    cmd = _docker_compose_cmd()
    if cmd is None:
        raise SystemExit("Docker Compose is required to run Dify. Please install Docker and Docker Compose.")

    env_file = docker_dir / ".env"
    env_example = docker_dir / ".env.example"
    if not env_file.exists() and env_example.exists():
        print(f"Creating Dify .env from {env_example} ...")
        shutil.copy(env_example, env_file)

    print("Booting Dify stack via Docker Compose ...")
    res = subprocess.run(cmd + ["up", "-d"], cwd=str(docker_dir), check=False)
    if res.returncode != 0:
        raise SystemExit(f"✗ Failed to start Dify (docker compose exited with code {res.returncode}).")
    print("\n✅ Dify stack is online! Access the UI at http://localhost/")


def stop_dify() -> None:
    """Stop the Dify Docker Compose stack."""
    require_supported_platform()
    docker_dir = find_dify()
    if docker_dir is None:
        print("Dify is not provisioned or extracted; nothing to stop.")
        return

    cmd = _docker_compose_cmd()
    if cmd is None:
        print("Docker Compose not found; cannot stop Dify containers.")
        return

    print("🛑 Stopping Dify Docker Compose stack ...")
    subprocess.run(cmd + ["down"], cwd=str(docker_dir), check=False)
    print("🧹 Dify resources cleaned up.")
