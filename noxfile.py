"""LocalCounsel automation pipeline (nox).

It provisions the local LLM stack (model weights + llama.cpp + AnythingLLM),
boots/stops the inference server, and runs the app and tests. This file holds
ONLY the nox session definitions; the ops logic lives in the sibling
``pipeline/`` package (app code stays clean under ``src/``).

Common sessions:
    nox -s provision   # idempotently download + extract everything
    nox -s boot_llm    # start llama-server and wait for it to be ready
    nox -s run         # boot the LLM (if needed) and run the assistant
    nox -s test        # boot the LLM (if needed) and run pytest
    nox -s okf         # verify the docs are a conformant OKF v0.1 bundle
    nox -s okf_semantic  # advisory LLM review of the docs (boots the LLM; slow)
    nox -s unit        # run the fast, LLM-free unit tests (no server boot)
    nox -s stop_llm    # stop the server and its child processes
    nox -s ui          # launch the AnythingLLM desktop UI
    nox -s dify        # launch the Dify web stack via Docker Compose (boots local LLM first)
    nox -s boot_dify   # start the Dify Docker Compose stack and local LLM
    nox -s stop_dify   # stop the Dify Docker Compose stack

The model is pluggable: override LC_MODEL_URL / LC_MODEL_NAME (and optionally
LC_LLAMA_URL) to run a different GGUF — e.g. DeepSeek instead of Gemma — with no
code changes.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import nox

# Make the sibling ops package importable regardless of how this file is loaded:
# this nox version imports the noxfile WITHOUT adding its directory to sys.path,
# so we insert it explicitly (idempotent; also covers plain `import noxfile`).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline.config import ANYTHINGLLM_APP, LOGS, REPORTS, ROOT
from pipeline.dify_setup import setup_dify
from pipeline.okf import check_okf, okf_concept_files
from pipeline.provisioning import provision as pipeline_provision
from pipeline.reporting import write_md_report
from pipeline.server import boot_dify as pipeline_boot_dify
from pipeline.server import boot_llm as pipeline_boot_llm
from pipeline.server import stop_dify as pipeline_stop_dify
from pipeline.server import stop_llm as pipeline_stop_llm
from pipeline.util import link_latest, safe_remove_dir, stamp

nox.options.sessions = ["okf", "unit", "test", "e2e"]
nox.options.reuse_existing_virtualenvs = True


@nox.session(python=False)
def okf(session: nox.Session) -> None:
    """Verify the repository docs are a conformant OKF v0.1 knowledge bundle.

    Fails if any non-reserved Markdown file lacks frontmatter with a ``type``, or
    if index.md is missing, does not list a concept, or lists a missing file. See
    the "OKF-Compliant Knowledge Bundle" NFR in docs/erasmus/requirements.md.
    """
    concepts = okf_concept_files()
    problems = check_okf()
    if problems:
        for p in problems:
            session.warn(f"✗ {p}")
        session.error(f"OKF conformance failed: {len(problems)} problem(s) across {len(concepts)} concept file(s).")
    session.log(f"✅ OKF v0.1 conformant — {len(concepts)} concept files, all with a 'type' and listed in index.md.")


@nox.session
def okf_semantic(session: nox.Session) -> None:
    """Advisory LLM semantic review of the OKF bundle (never fails on findings).

    Boots the local LLM, then asks it — one narrow question per call — whether
    each concept's description still matches its body and its index.md row.
    Findings are written to build/reports/okf-semantic-<stamp>.md (with a -latest
    pointer) and are ADVISORY: only infrastructure errors fail this session.
    NOT part of the default sessions — it boots the multi-GB LLM and is slow.
    """
    session.install("-e", ".")
    REPORTS.mkdir(parents=True, exist_ok=True)

    run_stamp = stamp(datetime.now(timezone.utc))
    report_path = REPORTS / f"okf-semantic-{run_stamp}.md"

    pipeline_boot_llm(run_stamp)
    session.run(
        "python", "-m", "local_counsel.okf_review",
        "--root", str(ROOT),
        "--out", str(report_path),
    )
    link_latest(report_path, REPORTS / "okf-semantic-latest.md")
    print(
        f"\nAdvisory report: {report_path}"
        f"\nLatest pointer : {REPORTS / 'okf-semantic-latest.md'}"
    )


@nox.session(python=False)
def provision(session: nox.Session) -> None:
    """Idempotently download + extract all models and binaries."""
    pipeline_provision()


@nox.session(python=False)
def boot_llm(session: nox.Session) -> None:
    """Boot the LLM server and wait until it is ready."""
    pipeline_boot_llm()


@nox.session(python=False)
def stop_llm(session: nox.Session) -> None:
    """Stop the LLM server (and its children) and clean up."""
    pipeline_stop_llm()


@nox.session
def run(session: nox.Session) -> None:
    """Boot the LLM (if needed) and run the assistant."""
    session.install("-e", ".")
    pipeline_boot_llm()
    session.run("python", "-m", "local_counsel.assistant")


@nox.session
def unit(session: nox.Session) -> None:
    """Run the fast, LLM-free unit tests (does NOT boot the LLM server)."""
    session.install("-e", ".[test]")
    session.run("pytest", "tests/unit")


def _provision_demo_stack(session: nox.Session) -> None:
    """Install deps + Chromium, and bring up the whole demo dependency chain.

    The pipeline owns every dependency (Rule 4): local LLM, the Dify Docker stack,
    and the provisioned Dify provider + Longevity Mentor app. Both end-to-end tests
    run **through Dify** (Dify → local Gemma 4), so this is shared by `demo` + `e2e`.
    Requires Docker.
    """
    session.install("-e", ".[demo]")
    # Idempotent: downloads the Chromium build only if missing (Playwright's cache).
    session.run("playwright", "install", "chromium")
    pipeline_boot_dify()
    setup_dify()  # registers local Gemma 4 provider + app; writes build/dify/*


@nox.session
def demo(session: nox.Session) -> None:
    """Run browser-driven end-to-end demos (Playwright), headed + slowed.

    Pick specific tests or enable debug/paused mode easily after ``--``:

        nox -s demo                          # run all demos headed + slowmo
        nox -s demo -- dify                  # run only test_dify_greeting_demo.py
        nox -s demo -- nutrition             # run only test_nutrition_advice_demo.py
        nox -s demo -- dify --debug          # run dify demo starting paused (--start-paused)
        nox -s demo -- --pause               # drop into Playwright Inspector step-by-step
    """
    _provision_demo_stack(session)
    posargs = list(session.posargs)

    targets: list[str] = []
    other_args: list[str] = []
    for arg in posargs:
        if arg in ("dify", "greeting"):
            targets.append("tests/end-to-end/test_dify_greeting_demo.py")
        elif arg in ("nutrition", "openehr"):
            targets.append("tests/end-to-end/test_nutrition_advice_demo.py")
        elif arg == "--debug":
            other_args.append("--start-paused")
        elif not arg.startswith("-n") and not arg.startswith("--numprocesses"):
            other_args.append(arg)

    if not targets and not any(a.startswith("tests/") or a.endswith(".py") for a in other_args):
        targets = ["tests/end-to-end"]

    args = [*targets, *other_args]
    if "--headed" not in args and "--headless" not in args:
        args.append("--headed")
    if not any(a.startswith("--slowmo") for a in args):
        args.extend(["--slowmo", "1200"])
    if "-s" not in args and "--capture" not in args:
        args.append("-s")
    if "-p" not in args and "no:xdist" not in args:
        args.extend(["-p", "no:xdist"])

    session.run("pytest", *args)


@nox.session
def e2e(session: nox.Session) -> None:
    """Final validation stage: run the end-to-end browser tests headless in parallel.

    Same tests as ``nox -s demo`` but headless and parallelized across CPU cores
    (via ``-n auto`` by default), serving as real pipeline validation (part of
    the default ``nox`` run). Every end-to-end test runs **through the provisioned
    Dify stack** — no skipping, no direct-to-model shortcut. Pass files/flags
    after ``--``.
    """
    _provision_demo_stack(session)
    args = list(session.posargs or ["tests/end-to-end"])
    if not any(arg.startswith("-n") or arg.startswith("--numprocesses") for arg in args):
        args = ["-n", "auto", *args]
    session.run("pytest", *args)


@nox.session
def test(session: nox.Session) -> None:
    """Boot the LLM (if needed) and run the integration tests.

    Produces, all under build/ (each named with a colon-free UTC ISO-8601 stamp,
    so runs are retained, with -latest pointers):
      - reports/test-report-<stamp>.md   — Markdown summary + per-test output
      - reports/pytest-junit-<stamp>.xml — JUnit XML
      - logs/pytest-<stamp>.log          — full pytest console transcript
      - logs/llama-<stamp>.log           — llama-server log (see pipeline.server)
    """
    session.install("-e", ".[test]")
    REPORTS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    run_stamp = stamp(now)
    xml_path = REPORTS / f"pytest-junit-{run_stamp}.xml"
    md_path = REPORTS / f"test-report-{run_stamp}.md"
    pytest_log = LOGS / f"pytest-{run_stamp}.log"

    pipeline_boot_llm(run_stamp)

    # Stream pytest live to the terminal AND persist a full transcript via tee.
    # pipefail propagates pytest's exit code through the pipe; [0, 1] lets a test
    # failure through so the report is still written (Linux x64 target — bash assumed).
    # The browser end-to-end tests run in the dedicated final `e2e` stage (below),
    # which installs Playwright + Chromium. Skip them here to avoid double runs and
    # so this stage needs no browser.
    session.run(
        "bash", "-c",
        f"set -o pipefail; pytest --ignore=tests/end-to-end --junitxml='{xml_path}' 2>&1 | tee '{pytest_log}'",
        success_codes=[0, 1],
        external=True,
    )
    totals = write_md_report(xml_path, md_path, now)

    # Convenience pointers to the most recent run.
    link_latest(md_path, REPORTS / "test-report-latest.md")
    link_latest(xml_path, REPORTS / "pytest-junit-latest.xml")
    link_latest(pytest_log, LOGS / "pytest-latest.log")

    print(
        f"\nArtifacts ({run_stamp}):"
        f"\n  report : {md_path}"
        f"\n  junit  : {xml_path}"
        f"\n  pytest log : {pytest_log}"
        f"\n  llama log  : {LOGS / f'llama-{run_stamp}.log'}"
        f"\n  latest report: {REPORTS / 'test-report-latest.md'}"
    )
    if not totals["ok"]:
        session.error(f"Tests failed — see {md_path}")


@nox.session(python=False)
def ui(session: nox.Session) -> None:
    """Launch the AnythingLLM desktop UI (boots the LLM first)."""
    pipeline_boot_llm()
    print("Booting AnythingLLM UI ...")
    if platform.system().lower() == "darwin":
        subprocess.run(["open", str(ANYTHINGLLM_APP)], check=False)
    else:  # Linux AppImage
        subprocess.run([str(ANYTHINGLLM_APP), "--appimage-extract-and-run"], check=False)


@nox.session(python=False)
def dify(session: nox.Session) -> None:
    """Launch the Dify stack via Docker Compose (boots the LLM first)."""
    pipeline_boot_dify()


@nox.session(python=False)
def boot_dify(session: nox.Session) -> None:
    """Boot the Dify stack and local LLM server."""
    pipeline_boot_dify()


@nox.session(python=False)
def stop_dify(session: nox.Session) -> None:
    """Stop the Dify Docker Compose stack."""
    pipeline_stop_dify()


@nox.session(python=False)
def push_github(session: nox.Session) -> None:
    """Create a private GitHub repository and push the code there."""
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


@nox.session(python=False)
def clean_logs(session: nox.Session) -> None:
    """Clean logs and test reports under build/ without deleting cache."""
    for folder in (LOGS, REPORTS):
        safe_remove_dir(session, folder)
    session.log("🧹 Logs and reports cleaned.")
