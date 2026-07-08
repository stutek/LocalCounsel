"""Unit tests for the deterministic OKF conformance checks (pipeline.okf).

The parsing helper (okf_index_ids) is pure and tested with handwritten inputs.
check_okf / okf_concept_files accept a ``root`` parameter, so we exercise both
tmp_path fake bundles (false-pass / dead-row / happy-path scenarios) and the real
repository — which must stay a conformant OKF v0.1 bundle (the same invariant
``nox -s okf`` enforces).
"""

from __future__ import annotations

from pathlib import Path

from pipeline import okf


def _write_concept(root: Path, rel: str, type_: str = "Note") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntype: {type_}\n---\n\n# {rel}\n", encoding="utf-8")


def _write_index(root: Path, concept_ids: list[str]) -> None:
    lines = [
        "# Fake bundle",
        "",
        "See the [OKF spec](https://example.test/okf/SPEC.md) for details.",
        "",
        "| Concept ID | Type | Description |",
        "| --- | --- | --- |",
    ]
    lines += [f"| [/{cid}](/{cid}.md) | Note | Fake. |" for cid in concept_ids]
    (root / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# _okf_index_ids — pure parsing helper                                          #
# --------------------------------------------------------------------------- #
def test_okf_index_ids_parses_link_targets():
    text = (
        "| [/README](/README.md) | Overview | ... |\n"
        "| [/docs/ARCHITECTURE](/docs/ARCHITECTURE.md) | Architecture | ... |\n"
    )
    assert okf.okf_index_ids(text) == {"README", "docs/ARCHITECTURE"}


def test_okf_index_ids_ignores_external_and_non_md_links():
    text = (
        "An [external spec](https://example.test/okf/SPEC.md) link.\n"
        "A [relative link](docs/foo.md) without leading slash is not a listing.\n"
        "A [non-md link](/LICENSE) is not a concept.\n"
        "| [/real/concept](/real/concept.md) | Note | ... |\n"
    )
    assert okf.okf_index_ids(text) == {"real/concept"}


def test_okf_index_ids_prefix_is_not_conflated():
    # docs/ARCH is a substring of docs/ARCHITECTURE; only exact link targets count.
    text = "| [/docs/ARCHITECTURE](/docs/ARCHITECTURE.md) | Architecture | ... |\n"
    ids = okf.okf_index_ids(text)
    assert "docs/ARCHITECTURE" in ids
    assert "docs/ARCH" not in ids


# --------------------------------------------------------------------------- #
# _check_okf on fake bundles (tmp_path)                                         #
# --------------------------------------------------------------------------- #
def test_check_okf_happy_path(tmp_path):
    _write_concept(tmp_path, "README.md")
    _write_concept(tmp_path, "docs/ARCHITECTURE.md")
    _write_index(tmp_path, ["README", "docs/ARCHITECTURE"])
    assert okf.check_okf(tmp_path) == []


def test_check_okf_prefix_false_pass_is_now_caught(tmp_path):
    # Old substring check false-passed: "docs/ARCH" is inside "docs/ARCHITECTURE".
    _write_concept(tmp_path, "docs/ARCHITECTURE.md")
    _write_concept(tmp_path, "docs/ARCH.md")  # NOT listed in the index
    _write_index(tmp_path, ["docs/ARCHITECTURE"])
    problems = okf.check_okf(tmp_path)
    assert problems == ["docs/ARCH.md: concept 'docs/ARCH' is not listed in index.md"]


def test_check_okf_dead_index_row_is_reported(tmp_path):
    _write_concept(tmp_path, "README.md")
    _write_index(tmp_path, ["README", "docs/deleted-doc"])  # file does not exist
    problems = okf.check_okf(tmp_path)
    assert problems == ["index.md: entry 'docs/deleted-doc' points at a missing file"]


def test_check_okf_missing_frontmatter_and_type(tmp_path):
    (tmp_path / "nofm.md").write_text("# no frontmatter\n", encoding="utf-8")
    (tmp_path / "notype.md").write_text("---\ntitle: x\n---\nbody\n", encoding="utf-8")
    _write_index(tmp_path, ["nofm", "notype"])
    problems = okf.check_okf(tmp_path)
    assert "nofm.md: missing YAML frontmatter block" in problems
    assert "notype.md: frontmatter has no non-empty 'type' field" in problems


def test_check_okf_missing_index(tmp_path):
    _write_concept(tmp_path, "README.md")
    problems = okf.check_okf(tmp_path)
    assert "index.md: missing bundle listing at the repository root" in problems


# --------------------------------------------------------------------------- #
# Real repository must stay conformant                                          #
# --------------------------------------------------------------------------- #
def test_okf_concept_files_excludes_reserved_and_generated():
    files = okf.okf_concept_files()
    assert files, "expected at least one OKF concept file in the repo"
    assert all(p.suffix == ".md" for p in files)

    names = {p.name for p in files}
    # Reserved bundle files are not concepts.
    assert names.isdisjoint(okf.OKF_RESERVED)

    # Generated/vendored trees are skipped.
    for p in files:
        rel_parts = p.relative_to(okf.ROOT).parts
        assert not any(part in okf.OKF_SKIP_DIRS for part in rel_parts)


def test_check_okf_reports_no_problems_for_real_repo():
    problems = okf.check_okf()
    assert problems == [], f"OKF conformance problems found: {problems}"
