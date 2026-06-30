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
import shutil
import signal
import subprocess
import tarfile
import time
import urllib.request
from datetime import datetime, timezone
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
REPORTS = BUILD / "reports"   # JUnit XML + Markdown test reports
LOGS = BUILD / "logs"         # llama-server + pytest run logs


def _stamp(dt: datetime) -> str:
    """UTC ISO-8601 timestamp, colon-free so it is filename-portable (Windows-safe)."""
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z").replace(":", "-")


def _link_latest(target: Path, link: Path) -> None:
    """Point ``link`` at ``target`` (symlink, copy fallback) for 'latest' convenience."""
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target.name)  # relative within the same dir
    except OSError:
        shutil.copyfile(target, link)


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
def _health_ok(host: str, port: int) -> bool:
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


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _tail(path: Path, n: int = 25) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return "(no log)"


def _boot_llm(log_stamp: str | None = None) -> None:
    """Start llama-server (if not already up) and wait for it to bind the port.

    The server is detached (own process group) and outlives this nox process, so
    its stdout/stderr are redirected to a persistent, timestamped log file under
    build/logs/ — tail it live with ``tail -f build/logs/llama-latest.log``.
    """
    if _health_ok(HOST, PORT):
        print(f"✓ LLM already serving on {HOST}:{PORT}")
        return

    _provision()
    server = _find_server()
    if server is None:
        raise SystemExit("llama-server binary not found after provisioning!")
    server.chmod(0o755)

    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"llama-{log_stamp or _stamp(datetime.now(timezone.utc))}.log"
    logf = open(log_path, "w")  # noqa: SIM115 — kept open for the detached server's lifetime
    _link_latest(log_path, LOGS / "llama-latest.log")

    print(f"Starting llama-server ... (logging to {log_path})")
    env = {**os.environ, "LD_LIBRARY_PATH": str(server.parent)}
    proc = subprocess.Popen(
        [str(server), "-m", str(MODEL_FILE), "--host", HOST, "--port", str(PORT)],
        cwd=str(server.parent),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # own process group → clean group-kill in stop_llm
    )
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(proc.pid))

    print(f"Waiting for LLM server on {HOST}:{PORT} to load the model ", end="", flush=True)
    for _ in range(180):  # model load can take a while for larger GGUFs
        if _health_ok(HOST, PORT):
            print("\n✅ LLM server is online!")
            return
        if proc.poll() is not None:
            raise SystemExit(
                f"llama-server exited early (code {proc.returncode}). Last log lines:\n{_tail(log_path)}"
            )
        print(".", end="", flush=True)
        time.sleep(1)

    proc.terminate()
    raise SystemExit(
        f"\nLLM server failed to start on {HOST}:{PORT}. Last log lines:\n{_tail(log_path)}"
    )


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
# Reporting                                                                    #
# --------------------------------------------------------------------------- #
def _write_md_report(xml_path: Path, md_path: Path, generated) -> dict:
    """Parse the JUnit XML pytest emitted and render a Markdown summary.

    Returns the totals dict (incl. ``ok``) so the session can set its exit status.
    Pure stdlib — no extra dependency.
    """
    import xml.etree.ElementTree as ET

    root = ET.parse(xml_path).getroot()
    suites = root.findall("testsuite") or ([root] if root.tag == "testsuite" else [])

    icon = {"passed": "✅", "failed": "❌", "error": "💥", "skipped": "⚪"}
    cases: list[dict] = []
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time": 0.0}
    for suite in suites:
        totals["tests"] += int(suite.get("tests", 0))
        totals["failures"] += int(suite.get("failures", 0))
        totals["errors"] += int(suite.get("errors", 0))
        totals["skipped"] += int(suite.get("skipped", 0))
        totals["time"] += float(suite.get("time", 0) or 0)
        for case in suite.findall("testcase"):
            failure, error, skipped = (case.find(t) for t in ("failure", "error", "skipped"))
            node = error if error is not None else failure if failure is not None else skipped
            outcome = (
                "error" if error is not None
                else "failed" if failure is not None
                else "skipped" if skipped is not None
                else "passed"
            )
            name = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
            detail = ((node.get("message") or node.text or "").strip()) if node is not None else ""
            sysout = (case.findtext("system-out") or "").strip()
            syserr = (case.findtext("system-err") or "").strip()
            cases.append({
                "name": name,
                "outcome": outcome,
                "time": float(case.get("time", 0) or 0),
                "detail": detail,
                "sysout": sysout,
                "syserr": syserr,
            })

    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    ok = totals["failures"] == 0 and totals["errors"] == 0

    lines = [
        "# LocalCounsel — Test Report",
        "",
        f"- **Generated:** {generated.isoformat(timespec='seconds').replace('+00:00', 'Z')}",
        f"- **Result:** {'✅ PASSED' if ok else '❌ FAILED'}",
        f"- **Totals:** {totals['tests']} tests · {passed} passed · "
        f"{totals['failures']} failed · {totals['errors']} errors · {totals['skipped']} skipped",
        f"- **Duration:** {totals['time']:.2f}s",
        "",
        "| Test | Outcome | Time |",
        "| --- | --- | --- |",
    ]
    lines += [f"| `{c['name']}` | {icon[c['outcome']]} {c['outcome']} | {c['time']:.2f}s |" for c in cases]

    failing = [c for c in cases if c["outcome"] in ("failed", "error")]
    if failing:
        lines += ["", "## Failures", ""]
        for c in failing:
            lines += [f"### `{c['name']}`", "", "```", c["detail"] or "(no detail)", "```", ""]

    # Per-test captured output (requires junit_logging=all in pyproject). Collapsed
    # so the report stays scannable; expand to observe stdout/stderr of any test.
    if any(c["sysout"] or c["syserr"] for c in cases):
        lines += ["", "## Captured output", ""]
        for c in cases:
            if not (c["sysout"] or c["syserr"]):
                continue
            lines += [f"<details><summary>{icon[c['outcome']]} <code>{c['name']}</code></summary>", ""]
            if c["sysout"]:
                lines += ["**stdout**", "", "```text", c["sysout"], "```", ""]
            if c["syserr"]:
                lines += ["**stderr**", "", "```text", c["syserr"], "```", ""]
            lines += ["</details>", ""]

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {**totals, "passed": passed, "ok": ok}


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
    """Boot the LLM (if needed) and run the integration tests.

    Produces, all under build/ (each named with a colon-free UTC ISO-8601 stamp,
    so runs are retained, with -latest pointers):
      - reports/test-report-<stamp>.md   — Markdown summary + per-test output
      - reports/pytest-junit-<stamp>.xml — JUnit XML
      - logs/pytest-<stamp>.log          — full pytest console transcript
      - logs/llama-<stamp>.log           — llama-server log (see _boot_llm)
    """
    session.install("-e", ".[test]")
    REPORTS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    stamp = _stamp(now)
    xml_path = REPORTS / f"pytest-junit-{stamp}.xml"
    md_path = REPORTS / f"test-report-{stamp}.md"
    pytest_log = LOGS / f"pytest-{stamp}.log"

    _boot_llm(stamp)

    # Stream pytest live to the terminal AND persist a full transcript via tee.
    # pipefail propagates pytest's exit code through the pipe; [0, 1] lets a test
    # failure through so the report is still written (Linux x64 target — bash assumed).
    session.run(
        "bash", "-c",
        f"set -o pipefail; pytest --junitxml='{xml_path}' 2>&1 | tee '{pytest_log}'",
        success_codes=[0, 1],
        external=True,
    )
    totals = _write_md_report(xml_path, md_path, now)

    # Convenience pointers to the most recent run.
    _link_latest(md_path, REPORTS / "test-report-latest.md")
    _link_latest(xml_path, REPORTS / "pytest-junit-latest.xml")
    _link_latest(pytest_log, LOGS / "pytest-latest.log")

    print(
        f"\nArtifacts ({stamp}):"
        f"\n  report : {md_path}"
        f"\n  junit  : {xml_path}"
        f"\n  pytest log : {pytest_log}"
        f"\n  llama log  : {LOGS / f'llama-{stamp}.log'}"
        f"\n  latest report: {REPORTS / 'test-report-latest.md'}"
    )
    if not totals["ok"]:
        session.error(f"Tests failed — see {md_path}")


@nox.session(python=False)
def ui(session: nox.Session) -> None:
    """Launch the AnythingLLM desktop UI (boots the LLM first)."""
    _boot_llm()
    print("Booting AnythingLLM UI ...")
    subprocess.run([str(ANYTHINGLLM_APP), "--appimage-extract-and-run"], check=False)
