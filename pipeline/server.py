"""llama-server lifecycle: health polling, boot, and shutdown."""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .config import CTX_SIZE, HOST, LOGS, MODEL_FILE, PID_FILE, PORT, require_supported_platform
from .provisioning import find_dify, find_server, provision
from .util import link_latest, stamp


def health_ok(host: str, port: int) -> bool:
    """True only once llama-server is fully ready.

    The server binds the port *before* the model finishes loading, answering
    /health with 503 ("Loading model") until ready and 200 afterwards. Polling the
    TCP port alone races the model load, so we check /health instead.
    """
    check_host = "127.0.0.1" if host == "0.0.0.0" else host
    try:
        with urllib.request.urlopen(f"http://{check_host}:{port}/health", timeout=2) as resp:
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


def _enforce_llm_port_firewall() -> None:
    """When bound to all interfaces, restrict the LLM port to loopback + Docker.

    llama-server must bind 0.0.0.0 to serve both host-loopback clients and the
    Dify containers, so we close the external exposure at the firewall instead.
    Best-effort: warn loudly (never abort) if the allow-list can't be installed.
    """
    if HOST != "0.0.0.0":
        return
    from .firewall import ensure_llm_port_firewall, is_llm_port_firewalled

    if is_llm_port_firewalled(PORT):
        return
    if ensure_llm_port_firewall(PORT):
        print(f"🔒 Firewalled port {PORT}: loopback + Docker subnets only (blocked on Wi-Fi/LAN).")
    else:
        print(
            f"⚠️  llama-server binds 0.0.0.0:{PORT} but the firewall allow-list is NOT active — "
            f"port {PORT} may be reachable on Wi-Fi/LAN.\n"
            f"    Harden it once with:  sudo nox -s secure_ports\n"
            f"    (or set LC_LLM_HOST=127.0.0.1 to bind loopback only — Dify then can't reach the model)."
        )


def boot_llm(log_stamp: str | None = None) -> None:
    """Start llama-server (if not already up) and wait for it to bind the port.

    The server is detached (own process group) and outlives this nox process, so
    its stdout/stderr are redirected to a persistent, timestamped log file under
    build/logs/ — tail it live with ``tail -f build/logs/llama-latest.log``.
    """
    require_supported_platform()
    _enforce_llm_port_firewall()
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
        [str(server), "-m", str(MODEL_FILE), "--host", HOST, "--port", str(PORT), "-c", str(CTX_SIZE), "-np", "1"],
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


def _check_docker_permissions(cmd: list[str]) -> None:
    """Verify Docker daemon socket access before attempting docker compose."""
    res = subprocess.run(cmd[:1] + ["ps"], capture_output=True, text=True, check=False)
    if res.returncode != 0 and "permission denied" in (res.stderr + res.stdout).lower():
        raise SystemExit(
            "✗ Permission denied connecting to Docker daemon socket (/var/run/docker.sock).\n\n"
            "  To fix this immediately for your current session, run:\n"
            "      sudo chmod 666 /var/run/docker.sock\n\n"
            "  Or permanently add your user to the docker group:\n"
            "      sudo usermod -aG docker $USER && newgrp docker\n"
        )


def run_docker_compose(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run docker compose with automatic group fallback ('sg docker') if needed."""
    base = _docker_compose_cmd()
    if base is None:
        raise SystemExit("Docker Compose is required to run Dify. Please install Docker and Docker Compose.")

    res_ps = subprocess.run(base[:1] + ["ps"], capture_output=True, text=True, check=False)
    if res_ps.returncode == 0:
        return subprocess.run(base + args, cwd=str(cwd), check=False)

    # Automatically run under 'docker' group if user is a member but session hasn't reloaded groups yet
    if shutil.which("sg") and subprocess.run(["sg", "docker", "-c", "docker ps"], capture_output=True).returncode == 0:
        cmd_str = " ".join(base + args)
        return subprocess.run(["sg", "docker", "-c", cmd_str], cwd=str(cwd), check=False)

    _check_docker_permissions(base)
    return subprocess.run(base + args, cwd=str(cwd), check=False)


def boot_dify(log_stamp: str | None = None) -> None:
    """Boot Dify stack via Docker Compose (boots local LLM first if needed)."""
    require_supported_platform()
    boot_llm(log_stamp=log_stamp)

    provision()
    docker_dir = find_dify()
    if docker_dir is None:
        raise SystemExit("Dify docker directory not found after provisioning!")

    env_file = docker_dir / ".env"
    env_example = docker_dir / ".env.example"
    if not env_file.exists() and env_example.exists():
        print(f"Creating Dify .env from {env_example} ...")
        shutil.copy(env_example, env_file)

    if env_file.exists():
        content = env_file.read_text(encoding="utf-8")
        patched = content.replace("TEXT_GENERATION_TIMEOUT_MS=60000\n", "TEXT_GENERATION_TIMEOUT_MS=600000\n")
        patched = patched.replace("GUNICORN_TIMEOUT=360\n", "GUNICORN_TIMEOUT=600\n")
        patched = patched.replace("API_WEBSOCKET_GUNICORN_TIMEOUT=360\n", "API_WEBSOCKET_GUNICORN_TIMEOUT=600\n")
        if "EXPOSE_NGINX_PORT=" in patched:
            patched = re.sub(r"^EXPOSE_NGINX_PORT=.*$", "EXPOSE_NGINX_PORT=127.0.0.1:80", patched, flags=re.MULTILINE)
        else:
            patched += "\nEXPOSE_NGINX_PORT=127.0.0.1:80\n"
        if patched != content:
            env_file.write_text(patched, encoding="utf-8")

    print("Booting Dify stack via Docker Compose ...")
    res = run_docker_compose(["up", "-d"], cwd=docker_dir)
    if res.returncode != 0:
        raise SystemExit(f"✗ Failed to start Dify (docker compose exited with code {res.returncode}).")
    run_docker_compose(["restart", "nginx"], cwd=docker_dir)
    from .dify_setup import setup_dify
    url = setup_dify()
    print(f"\n✅ Dify stack is online! Longevity Mentor chat URL: {url}")


def stop_dify() -> None:
    """Stop the Dify Docker Compose stack."""
    require_supported_platform()
    docker_dir = find_dify()
    if docker_dir is None:
        print("Dify is not provisioned or extracted; nothing to stop.")
        return

    print("🛑 Stopping Dify Docker Compose stack ...")
    run_docker_compose(["down"], cwd=docker_dir)
    print("🧹 Dify resources cleaned up.")


def stop_anythingllm() -> None:
    """Stop running AnythingLLM UI processes."""
    stopped = False
    for pattern in ["AnythingLLM", "anythingllm"]:
        res = subprocess.run(["pkill", "-f", pattern], capture_output=True, check=False)
        if res.returncode == 0:
            stopped = True
    if stopped:
        print("🛑 Stopped AnythingLLM desktop UI process.")
    else:
        print("AnythingLLM UI is not running.")


def stop_all() -> None:
    """Stop Dify stack, AnythingLLM UI, and local LLM server."""
    print("🛑 Stopping all LocalCounsel services ...")
    stop_dify()
    stop_anythingllm()
    stop_llm()
    print("🧹 All processes stopped and memory cleaned up.")
