"""Advisory semantic review of the OKF knowledge bundle using the local LLM.

The deterministic OKF gate (``nox -s okf``) checks *structure* — frontmatter,
``type`` fields, index listings. This module asks the local model about *meaning*:
does a concept's frontmatter ``description`` still match its body, and does the
index.md row still match the frontmatter? Docs drift semantically as they are
edited; no regex can see that.

This stage is ADVISORY by design: findings are printed and written to a Markdown
report, but they never fail the build. The process exits non-zero only on
infrastructure errors (e.g. the LLM server is unreachable). Small local models
are unreliable reviewers, so every verdict requires human judgement.

Run via ``nox -s okf_semantic`` (which boots the local server first), or directly:

    python -m local_counsel.okf_review --root . --out report.md
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Deterministic concept discovery, deliberately self-contained: this is app code
# under src/ and must not import the ops-side noxfile. The reserved names, skip
# dirs, and frontmatter grammar mirror the OKF gate's definitions — keep in sync.
RESERVED_FILES = {"index.md", "log.md"}
SKIP_DIRS = {".git", ".nox", "build", ".pytest_cache", "__pycache__", "node_modules"}
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)
META_LINE_RE = re.compile(r"^([A-Za-z_][\w-]*):[ \t]*(.*?)[ \t]*$")
INDEX_ROW_RE = re.compile(r"\|\s*\[[^\]]*\]\((/[^)\s]+?)\.md\)\s*\|([^|]*)\|([^|]*)\|")

# Small local models can have a limited *reliable* working context; keep prompts
# narrow (one document, one question per call) and truncate bodies so prompt +
# reply always fit, regardless of the booted GGUF (e.g. gemma-4-E2B).
MAX_BODY_CHARS = 6000

VERDICTS = ("PASS", "FLAG", "INCONCLUSIVE")


@dataclass
class Concept:
    concept_id: str
    path: Path
    meta: dict[str, str]
    body: str


@dataclass
class Finding:
    concept_id: str
    check: str          # "description-drift" | "index-drift"
    verdict: str        # PASS | FLAG | INCONCLUSIVE
    detail: str = ""    # the model's (trimmed) reply


@dataclass
class ReviewResult:
    concepts_reviewed: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def flags(self) -> int:
        return sum(1 for f in self.findings if f.verdict == "FLAG")

    @property
    def inconclusive(self) -> int:
        return sum(1 for f in self.findings if f.verdict == "INCONCLUSIVE")


# --------------------------------------------------------------------------- #
# Deterministic parsing & discovery (LLM-free, unit-testable)                   #
# --------------------------------------------------------------------------- #
def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a Markdown doc into (frontmatter dict, body).

    Minimal ``key: value`` parsing — enough for the flat frontmatter this bundle
    uses; nested YAML is out of scope. Missing frontmatter yields ({}, full text).
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        lm = META_LINE_RE.match(line)
        if lm:
            meta[lm.group(1)] = lm.group(2).strip("\"'")
    return meta, m.group(2)


def discover_concepts(root: Path) -> list[Concept]:
    """Deterministically walk ``root`` for OKF concept files (same rules as the gate)."""
    concepts: list[Concept] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(p in SKIP_DIRS or p.endswith(".egg-info") for p in rel.parts[:-1]):
            continue
        if path.name in RESERVED_FILES:
            continue
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        concepts.append(Concept(rel.as_posix()[:-3], path, meta, body))
    return concepts


def index_descriptions(index_text: str) -> dict[str, str]:
    """Map concept ID -> description column, parsed from index.md table rows."""
    out: dict[str, str] = {}
    for m in INDEX_ROW_RE.finditer(index_text):
        out[m.group(1)[1:]] = m.group(3).strip()
    return out


# --------------------------------------------------------------------------- #
# Prompts & verdict parsing                                                     #
# --------------------------------------------------------------------------- #
_VERDICT_INSTRUCTION = (
    'Reply on the first line with exactly "VERDICT: PASS" or "VERDICT: FLAG", '
    "then one sentence of reasoning."
)


def build_description_prompt(description: str, body: str) -> str:
    """One doc, one question: does the metadata description match the body?"""
    return (
        "You are reviewing the metadata of a documentation file.\n\n"
        f"METADATA DESCRIPTION:\n{description}\n\n"
        f"DOCUMENT BODY (may be truncated):\n{body[:MAX_BODY_CHARS]}\n\n"
        "Question: Does this description accurately summarize the document body? "
        + _VERDICT_INSTRUCTION
    )


def build_index_prompt(doc_description: str, index_description: str) -> str:
    """One pair, one question: is the catalog row consistent with the doc metadata?"""
    return (
        "You are reviewing a documentation catalog for consistency.\n\n"
        f"DESCRIPTION IN THE DOCUMENT'S OWN METADATA:\n{doc_description}\n\n"
        f"DESCRIPTION IN THE CATALOG INDEX:\n{index_description}\n\n"
        "Question: Are these two descriptions consistent with each other (same "
        "subject and scope, no contradiction)? " + _VERDICT_INSTRUCTION
    )


def parse_verdict(reply: str) -> str:
    """Leniently extract PASS/FLAG from a model reply; anything else is INCONCLUSIVE.

    Small models are unreliable formatters — search case-insensitively for the
    first "VERDICT:" marker and read the word after it, instead of trusting exact
    first-line formatting. Unparseable output must be recorded, never crash.
    """
    m = re.search(r"verdict\s*(?:is)?\s*:?\s*(pass|flag)\b", reply or "", re.I)
    if m:
        return m.group(1).upper()
    return "INCONCLUSIVE"


# --------------------------------------------------------------------------- #
# Review loop                                                                   #
# --------------------------------------------------------------------------- #
def _trim(reply: str, limit: int = 400) -> str:
    reply = (reply or "").strip()
    return reply if len(reply) <= limit else reply[:limit] + " …"


def review_bundle(
    root: Path,
    ask_fn: Callable[[str], str],
    limit: int | None = None,
) -> ReviewResult:
    """Run the semantic checks over every concept in ``root``.

    ``ask_fn`` is injected so tests can run without an LLM. Exceptions from
    ``ask_fn`` propagate — they are infrastructure errors, handled by main().
    """
    result = ReviewResult()
    index_path = root / "index.md"
    idx_desc = (
        index_descriptions(index_path.read_text(encoding="utf-8"))
        if index_path.exists()
        else {}
    )

    concepts = discover_concepts(root)
    if limit is not None:
        concepts = concepts[:limit]

    for concept in concepts:
        result.concepts_reviewed += 1
        description = concept.meta.get("description", "").strip()

        # Check (a): frontmatter description vs document body. Skipped when there
        # is no description — that is a structural matter, not a semantic one.
        if description:
            reply = ask_fn(build_description_prompt(description, concept.body))
            result.findings.append(
                Finding(concept.concept_id, "description-drift", parse_verdict(reply), _trim(reply))
            )

        # Check (b): frontmatter description vs index.md row description. Skipped
        # when the concept is unlisted — the deterministic gate reports that.
        row = idx_desc.get(concept.concept_id, "").strip()
        if description and row:
            reply = ask_fn(build_index_prompt(description, row))
            result.findings.append(
                Finding(concept.concept_id, "index-drift", parse_verdict(reply), _trim(reply))
            )
    return result


# --------------------------------------------------------------------------- #
# Reporting                                                                     #
# --------------------------------------------------------------------------- #
def render_report(result: ReviewResult, generated: datetime, model_label: str) -> str:
    """Render the advisory findings as Markdown."""
    icon = {"PASS": "✅", "FLAG": "🚩", "INCONCLUSIVE": "❓"}
    lines = [
        "# LocalCounsel — OKF Semantic Review (Advisory)",
        "",
        "> **AI-generated advisory output — requires human review.** Produced by a",
        f"> small local model ({model_label}); verdicts are suggestions, not facts,",
        "> and this stage never gates the build.",
        "",
        f"- **Generated:** {generated.isoformat(timespec='seconds').replace('+00:00', 'Z')}",
        f"- **Concepts reviewed:** {result.concepts_reviewed}",
        f"- **Checks:** {len(result.findings)} · "
        f"🚩 {result.flags} flagged · ❓ {result.inconclusive} inconclusive",
        "",
        "| Concept | Check | Verdict |",
        "| --- | --- | --- |",
    ]
    lines += [
        f"| `{f.concept_id}` | {f.check} | {icon[f.verdict]} {f.verdict} |"
        for f in result.findings
    ]

    notable = [f for f in result.findings if f.verdict != "PASS"]
    if notable:
        lines += ["", "## Flagged / inconclusive checks", ""]
        for f in notable:
            lines += [
                f"### `{f.concept_id}` — {f.check} ({f.verdict})",
                "",
                "> " + (f.detail.replace("\n", "\n> ") or "(empty model reply)"),
                "",
            ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CLI                                                                           #
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Advisory semantic review of the OKF bundle via the local LLM."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Bundle root (default: cwd)")
    parser.add_argument("--out", type=Path, default=None, help="Markdown report path (default: stdout)")
    parser.add_argument("--limit", type=int, default=None, help="Review only the first N concepts")
    args = parser.parse_args(argv)

    from .assistant import ask  # imported lazily so LLM-free callers avoid openai
    from .config import load_settings

    settings = load_settings()
    print(f"OKF semantic review (advisory) — model '{settings.model_name}' at {settings.base_url}")

    try:
        result = review_bundle(args.root.resolve(), ask, limit=args.limit)
    except Exception as exc:  # infrastructure error (LLM unreachable, HTTP, …)
        print(f"ERROR: semantic review could not run: {exc}", file=sys.stderr)
        return 1

    report = render_report(result, datetime.now(timezone.utc), settings.model_name)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Report written to {args.out}")
    else:
        print(report)

    print(
        f"Summary: {result.concepts_reviewed} concepts · {len(result.findings)} checks · "
        f"{result.flags} flagged · {result.inconclusive} inconclusive"
    )
    # Advisory stage: findings never fail the build.
    return 0


if __name__ == "__main__":
    sys.exit(main())
