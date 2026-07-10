"""Deterministic OKF v0.1 knowledge-bundle conformance checks.

See the "OKF-Compliant Knowledge Bundle" NFR in docs/erasmus/requirements.md.
The advisory *semantic* review lives in ``src/local_counsel/okf_review.py`` (app
code, uses the LLM); this module is the pure-stdlib structural gate.
"""

from __future__ import annotations

import re
from pathlib import Path

from .config import ROOT

OKF_RESERVED = {"index.md", "log.md"}          # bundle files, not concepts
OKF_SKIP_DIRS = {".git", ".nox", "build", ".pytest_cache", "__pycache__", "node_modules"}


def okf_concept_files(root: Path = ROOT) -> list[Path]:
    """Every repository Markdown file that OKF treats as a *concept*.

    Skips generated/vendored trees and the reserved bundle files (index.md,
    log.md), which are not concepts. ``root`` is parameterizable for tests.
    """
    out = []
    for path in sorted(root.rglob("*.md")):
        rel_parts = path.relative_to(root).parts[:-1]
        if any(p in OKF_SKIP_DIRS or p.endswith(".egg-info") for p in rel_parts):
            continue
        if path.name in OKF_RESERVED:
            continue
        out.append(path)
    return out


def okf_index_ids(index_text: str) -> set[str]:
    """Concept IDs listed in index.md, parsed from its markdown link targets.

    Only root-relative targets of the form ``[...](/path/to/file.md)`` count as
    bundle listings (per the index table convention); external URLs (e.g. the OKF
    spec link) are ignored. The returned IDs have no leading slash and no ``.md``,
    matching a concept's canonical ID.

    Parsing real link targets — instead of substring-searching the whole file —
    prevents false passes where one concept ID is a prefix/substring of another
    (e.g. ``docs/ARCH`` matching inside ``docs/ARCHITECTURE``).
    """
    ids: set[str] = set()
    for target in re.findall(r"\]\((/[^)\s]+?\.md)\)", index_text):
        ids.add(target[1:-3])  # strip leading "/" and trailing ".md"
    return ids


def check_okf(root: Path = ROOT) -> list[str]:
    """Return a list of OKF v0.1 conformance problems (empty == conformant).

    Pure stdlib: a concept just needs a top-of-file YAML frontmatter block with a
    non-empty ``type``. We also enforce this project's NFR that a root index.md
    exists and lists every concept — and, conversely, that every index entry
    points at an existing concept file (no dead rows after deletes/renames).
    """
    problems: list[str] = []
    index_path = root / "index.md"
    index_text = index_path.read_text(encoding="utf-8") if index_path.exists() else None
    if index_text is None:
        problems.append("index.md: missing bundle listing at the repository root")
    listed_ids = okf_index_ids(index_text) if index_text is not None else set()

    concept_ids: set[str] = set()
    for path in okf_concept_files(root):
        rel = path.relative_to(root)
        concept_id = rel.as_posix()[:-3]  # path minus ".md"
        concept_ids.add(concept_id)
        text = path.read_text(encoding="utf-8", errors="replace")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not m:
            problems.append(f"{rel}: missing YAML frontmatter block")
            continue
        tm = re.search(r"^type:[ \t]*(\S.*?)\s*$", m.group(1), re.M)
        if not tm:
            problems.append(f"{rel}: frontmatter has no non-empty 'type' field")
        if index_text is not None and concept_id not in listed_ids:
            problems.append(f"{rel}: concept '{concept_id}' is not listed in index.md")

    # Reverse direction: index rows must point at files that actually exist.
    for dead_id in sorted(listed_ids - concept_ids):
        problems.append(f"index.md: entry '{dead_id}' points at a missing file")
    return problems
