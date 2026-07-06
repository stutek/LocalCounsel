"""LocalCounsel automation pipeline (nox).

It provisions the local LLM stack (model weights + llama.cpp + AnythingLLM),
boots/stops the inference server, and runs the app and tests. All ops logic lives
here; the application code stays clean under ``src/``.

Common sessions:
    nox -s provision   # idempotently download + extract everything
    nox -s boot_llm    # start llama-server and wait for it to be ready
    nox -s run         # boot the LLM (if needed) and run the assistant
    nox -s test        # boot the LLM (if needed) and run pytest
    nox -s okf         # verify the docs are a conformant OKF v0.1 bundle
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


import platform

def _get_llama_defaults() -> tuple[str, str]:
    sys_name = platform.system().lower()
    mach_name = platform.machine().lower()
    if sys_name == "linux":
        if "x86_64" in mach_name or "amd64" in mach_name:
            return "https://github.com/ggml-org/llama.cpp/releases/download/b9487/llama-b9487-bin-ubuntu-x64.tar.gz", "llama.tar.gz"
        return "https://github.com/ggml-org/llama.cpp/releases/download/b9487/llama-b9487-bin-ubuntu-arm64.tar.gz", "llama.tar.gz"
    elif sys_name == "darwin":
        if "arm" in mach_name:
            return "https://github.com/ggml-org/llama.cpp/releases/download/b9487/llama-b9487-bin-macos-arm64.tar.gz", "llama.tar.gz"
        return "https://github.com/ggml-org/llama.cpp/releases/download/b9487/llama-b9487-bin-macos-x64.tar.gz", "llama.tar.gz"
    elif sys_name == "windows":
        return "https://github.com/ggml-org/llama.cpp/releases/download/b9487/llama-b9487-bin-win-llvm-x64.zip", "llama.zip"
    return "https://github.com/ggml-org/llama.cpp/releases/download/b9487/llama-b9487-bin-ubuntu-x64.tar.gz", "llama.tar.gz"

def _get_anythingllm_defaults() -> tuple[str, str]:
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        return "https://cdn.anythingllm.com/latest/AnythingLLMDesktop.dmg", "AnythingLLMDesktop.dmg"
    elif sys_name == "windows":
        return "https://cdn.anythingllm.com/latest/AnythingLLMDesktop.exe", "AnythingLLMDesktop.exe"
    return "https://cdn.anythingllm.com/latest/AnythingLLMDesktop.AppImage", "AnythingLLMDesktop.AppImage"

_llama_url_default, _llama_name_default = _get_llama_defaults()
_allm_url_default, _allm_name_default = _get_anythingllm_defaults()

MODEL_URL = _env(
    "LC_MODEL_URL",
    "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q4_K_M.gguf",
)
MODEL_FILE = DOWNLOADS / _env("LC_MODEL_FILE", MODEL_URL.rsplit("/", 1)[-1])

LLAMA_URL = _env("LC_LLAMA_URL", _llama_url_default)
LLAMA_TAR = DOWNLOADS / _env("LC_LLAMA_FILE", _llama_name_default)

ANYTHINGLLM_URL = _env("LC_ANYTHINGLLM_URL", _allm_url_default)
ANYTHINGLLM_APP = DOWNLOADS / _env("LC_ANYTHINGLLM_FILE", _allm_name_default)

HOST = _env("LC_LLM_HOST", "127.0.0.1")
PORT = int(_env("LC_LLM_PORT", "8080"))

nox.options.sessions = ["okf", "test"]
nox.options.reuse_existing_virtualenvs = True

# OKF (Open Knowledge Format) knowledge-bundle conformance — see the
# "OKF-Compliant Knowledge Bundle" NFR in requirements/requirements.md.
OKF_RESERVED = {"index.md", "log.md"}          # bundle files, not concepts
OKF_INDEX = ROOT / "index.md"
OKF_SKIP_DIRS = {".git", ".nox", "build", ".pytest_cache", "__pycache__", "node_modules"}


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
    """Extract the llama.cpp archive (tarball or zip).

    Python's tarfile/zipfile extract archives natively, handling symlinks and platform specific files.
    """
    server = _find_server()
    if server is not None:
        print("✓ llama.cpp already extracted")
        return
    LLAMA_DIR.mkdir(parents=True, exist_ok=True)
    print("⇲ extracting llama.cpp ...")
    if LLAMA_TAR.suffix == ".zip" or LLAMA_TAR.name.endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(LLAMA_TAR, "r") as zip_ref:
            zip_ref.extractall(LLAMA_DIR)
    else:
        with tarfile.open(LLAMA_TAR, "r:gz") as tar:
            try:
                tar.extractall(LLAMA_DIR, filter="data")  # py3.12+ safe filter
            except TypeError:
                tar.extractall(LLAMA_DIR)


def _find_server() -> Path | None:
    if not LLAMA_DIR.exists():
        return None
    names = ("llama-server", "server", "llama-server.exe", "server.exe")
    for name in names:
        for path in LLAMA_DIR.rglob(name):
            if path.is_file():
                return path
    return None


def _provision() -> None:
    _download(MODEL_URL, MODEL_FILE)
    _download(LLAMA_URL, LLAMA_TAR)
    _extract_llama()
    _download(ANYTHINGLLM_URL, ANYTHINGLLM_APP)
    if platform.system().lower() != "windows":
        try:
            ANYTHINGLLM_APP.chmod(0o755)
        except OSError:
            pass


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
    if platform.system().lower() != "windows":
        try:
            server.chmod(0o755)
        except OSError:
            pass

    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"llama-{log_stamp or _stamp(datetime.now(timezone.utc))}.log"
    logf = open(log_path, "w")  # noqa: SIM115 — kept open for the detached server's lifetime
    _link_latest(log_path, LOGS / "llama-latest.log")

    print(f"Starting llama-server ... (logging to {log_path})")
    env = {**os.environ}
    if platform.system().lower() != "windows":
        env["LD_LIBRARY_PATH"] = str(server.parent)
        
    kwargs = {}
    if platform.system().lower() != "windows":
        kwargs["start_new_session"] = True
    else:
        # DETACHED_PROCESS = 0x00000008
        kwargs["creationflags"] = 0x00000008

    proc = subprocess.Popen(
        [str(server), "-m", str(MODEL_FILE), "--host", HOST, "--port", str(PORT)],
        cwd=str(server.parent),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
        **kwargs,
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
        is_win = platform.system().lower() == "windows"
        if not is_win:
            pgid = os.getpgid(pid)
            print(f"🛑 Stopping LLM server (PID {pid}) and child processes ...")
            os.killpg(pgid, signal.SIGTERM)
        else:
            print(f"🛑 Stopping LLM server (PID {pid}) ...")
            os.kill(pid, signal.SIGTERM)
            
        for _ in range(10):
            if not _pid_alive(pid):
                break
            time.sleep(0.5)
            
        if _pid_alive(pid):
            if not is_win:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
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
# OKF conformance                                                              #
# --------------------------------------------------------------------------- #
def _okf_concept_files() -> list[Path]:
    """Every repository Markdown file that OKF treats as a *concept*.

    Skips generated/vendored trees and the reserved bundle files (index.md,
    log.md), which are not concepts.
    """
    out = []
    for path in sorted(ROOT.rglob("*.md")):
        rel_parts = path.relative_to(ROOT).parts[:-1]
        if any(p in OKF_SKIP_DIRS or p.endswith(".egg-info") for p in rel_parts):
            continue
        if path.name in OKF_RESERVED:
            continue
        out.append(path)
    return out


def _check_okf() -> list[str]:
    """Return a list of OKF v0.1 conformance problems (empty == conformant).

    Pure stdlib: a concept just needs a top-of-file YAML frontmatter block with a
    non-empty ``type``. We also enforce this project's NFR that a root index.md
    exists and lists every concept.
    """
    import re

    problems: list[str] = []
    index_text = OKF_INDEX.read_text(encoding="utf-8") if OKF_INDEX.exists() else None
    if index_text is None:
        problems.append("index.md: missing bundle listing at the repository root")

    for path in _okf_concept_files():
        rel = path.relative_to(ROOT)
        concept_id = rel.as_posix()[:-3]  # path minus ".md"
        text = path.read_text(encoding="utf-8", errors="replace")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not m:
            problems.append(f"{rel}: missing YAML frontmatter block")
            continue
        tm = re.search(r"^type:[ \t]*(\S.*?)\s*$", m.group(1), re.M)
        if not tm:
            problems.append(f"{rel}: frontmatter has no non-empty 'type' field")
        if index_text is not None and concept_id not in index_text:
            problems.append(f"{rel}: concept '{concept_id}' is not listed in index.md")
    return problems


# --------------------------------------------------------------------------- #
# Sessions                                                                     #
# --------------------------------------------------------------------------- #
@nox.session(python=False)
def okf(session: nox.Session) -> None:
    """Verify the repository docs are a conformant OKF v0.1 knowledge bundle.

    Fails if any non-reserved Markdown file lacks frontmatter with a ``type``, or
    if index.md is missing or does not list a concept. See the "OKF-Compliant
    Knowledge Bundle" NFR in requirements/requirements.md.
    """
    concepts = _okf_concept_files()
    problems = _check_okf()
    if problems:
        for p in problems:
            session.warn(f"✗ {p}")
        session.error(f"OKF conformance failed: {len(problems)} problem(s) across {len(concepts)} concept file(s).")
    session.log(f"✅ OKF v0.1 conformant — {len(concepts)} concept files, all with a 'type' and listed in index.md.")


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
    system = platform.system().lower()
    if system == "darwin":
        subprocess.run(["open", str(ANYTHINGLLM_APP)], check=False)
    elif system == "windows":
        subprocess.run([str(ANYTHINGLLM_APP)], check=False)
    else:
        subprocess.run([str(ANYTHINGLLM_APP), "--appimage-extract-and-run"], check=False)


@nox.session(python=False)
def push_github(session: nox.Session) -> None:
    """Create a private GitHub repository and push the code there."""
    import shutil
    import subprocess
    
    # 1. Check if gh CLI is installed
    if shutil.which("gh") is None:
        session.error("GitHub CLI (gh) is not installed. Please install it and log in using 'gh auth login'.")
        
    # 2. Check if gh CLI is logged in
    res = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if res.returncode != 0:
        session.error("You are not logged into GitHub CLI. Please run 'gh auth login' first on your terminal.")
        
    # 3. Get the current git branch name
    res_branch = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True)
    branch = res_branch.stdout.strip() or "main"
        
    # 4. Check if origin remote exists
    res_remote = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True)
    if res_remote.returncode == 0:
        session.log(f"Remote origin already exists: {res_remote.stdout.strip()}")
        session.run("git", "push", "-u", "origin", branch, external=True)
        return
        
    # 5. Create repository and push
    repo_name = ROOT.name
    session.log(f"Creating private GitHub repository '{repo_name}'...")
    session.run("gh", "repo", "create", repo_name, "--private", "--source=.", "--push", external=True)


def _safe_remove_dir(session: nox.Session, path: Path) -> None:
    """Wipes a directory only if it passes strict path containment checks."""
    import shutil
    
    # 1. Resolve paths to absolute paths to prevent symlink tricks
    abs_path = path.resolve()
    abs_root = ROOT.resolve()
    abs_build = BUILD.resolve()
    
    # 2. Check path containment (must be strictly inside BUILD, which is inside ROOT)
    try:
        abs_path.relative_to(abs_build)
        abs_path.relative_to(abs_root)
    except ValueError:
        session.error(f"Safety Check Failed: Path '{abs_path}' is outside the authorized build directory.")
        return
        
    # 3. Prevent deleting critical parent directories
    if abs_path in (abs_root, abs_build):
        session.error(f"Safety Check Failed: Attempted to delete critical folder '{abs_path}'.")
        return
        
    # 4. Folder name specific guard
    if abs_path.name not in ("logs", "reports"):
        session.error(f"Safety Check Failed: Folder name '{abs_path.name}' is not allowed for log cleaning.")
        return
        
    # If all checks pass, delete it
    if abs_path.exists():
        session.log(f"Removing {abs_path} ...")
        shutil.rmtree(abs_path)


@nox.session(python=False)
def clean_logs(session: nox.Session) -> None:
    """Clean logs and test reports under build/ without deleting cache."""
    for folder in (LOGS, REPORTS):
        _safe_remove_dir(session, folder)
    session.log("🧹 Logs and reports cleaned.")


