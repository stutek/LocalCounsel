"""Unit tests for local_counsel.okf_review — fully LLM-free (ask_fn injected)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from local_counsel import okf_review


def _concept_md(description: str, body: str = "Some body.") -> str:
    return f'---\ntype: Note\ndescription: "{description}"\n---\n\n{body}\n'


def _make_bundle(root: Path) -> None:
    (root / "README.md").write_text(_concept_md("Project overview."), encoding="utf-8")
    docs = root / "docs"
    docs.mkdir()
    (docs / "arch.md").write_text(_concept_md("The architecture."), encoding="utf-8")
    # Reserved + skipped trees must be ignored.
    (root / "index.md").write_text(
        "| Concept ID | Type | Description |\n"
        "| --- | --- | --- |\n"
        "| [/README](/README.md) | Note | Project overview. |\n"
        "| [/docs/arch](/docs/arch.md) | Note | Totally different topic. |\n",
        encoding="utf-8",
    )
    (root / "log.md").write_text("reserved, not a concept\n", encoding="utf-8")
    build = root / "build" / "reports"
    build.mkdir(parents=True)
    (build / "old-report.md").write_text("generated\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Deterministic pieces                                                          #
# --------------------------------------------------------------------------- #
def test_parse_frontmatter():
    meta, body = okf_review.parse_frontmatter('---\ntype: Note\ndescription: "A b."\n---\nBody.')
    assert meta == {"type": "Note", "description": "A b."}
    assert body == "Body."


def test_parse_frontmatter_missing_block():
    meta, body = okf_review.parse_frontmatter("# just a body\n")
    assert meta == {}
    assert body == "# just a body\n"


def test_discover_concepts_skips_reserved_and_generated(tmp_path):
    _make_bundle(tmp_path)
    concepts = okf_review.discover_concepts(tmp_path)
    assert [c.concept_id for c in concepts] == ["README", "docs/arch"]
    assert concepts[0].meta["description"] == "Project overview."


def test_index_descriptions(tmp_path):
    _make_bundle(tmp_path)
    idx = okf_review.index_descriptions((tmp_path / "index.md").read_text(encoding="utf-8"))
    assert idx == {"README": "Project overview.", "docs/arch": "Totally different topic."}


def test_parse_verdict_lenient():
    assert okf_review.parse_verdict("VERDICT: PASS\nLooks fine.") == "PASS"
    assert okf_review.parse_verdict("  verdict:flag — description is stale") == "FLAG"
    assert okf_review.parse_verdict("Sure! The verdict is: Pass, I think.") == "PASS"
    assert okf_review.parse_verdict("I cannot help with that.") == "INCONCLUSIVE"
    assert okf_review.parse_verdict("") == "INCONCLUSIVE"
    assert okf_review.parse_verdict(None) == "INCONCLUSIVE"


def test_prompts_are_narrow_and_truncated():
    huge_body = "x" * (okf_review.MAX_BODY_CHARS * 2)
    prompt = okf_review.build_description_prompt("desc", huge_body)
    assert len(prompt) < okf_review.MAX_BODY_CHARS + 1000
    assert "VERDICT: PASS" in prompt and "VERDICT: FLAG" in prompt
    assert "VERDICT: FLAG" in okf_review.build_index_prompt("a", "b")


# --------------------------------------------------------------------------- #
# Review loop with an injected fake model                                       #
# --------------------------------------------------------------------------- #
def test_review_bundle_with_fake_llm(tmp_path):
    _make_bundle(tmp_path)
    replies = iter(
        [
            "VERDICT: PASS\nDescription matches.",       # README description-drift
            "VERDICT: PASS\nConsistent.",                 # README index-drift
            "VERDICT: PASS\nFine.",                       # docs/arch description-drift
            "VERDICT: FLAG\nIndex row is about something else.",  # docs/arch index-drift
        ]
    )
    result = okf_review.review_bundle(tmp_path, lambda prompt: next(replies))

    assert result.concepts_reviewed == 2
    assert len(result.findings) == 4
    assert result.flags == 1
    assert result.inconclusive == 0
    flagged = [f for f in result.findings if f.verdict == "FLAG"]
    assert flagged[0].concept_id == "docs/arch"
    assert flagged[0].check == "index-drift"


def test_review_bundle_skips_checks_without_inputs(tmp_path):
    # No description in frontmatter and not listed in any index -> zero checks.
    (tmp_path / "bare.md").write_text("---\ntype: Note\n---\nBody.\n", encoding="utf-8")
    result = okf_review.review_bundle(tmp_path, lambda p: (_ for _ in ()).throw(AssertionError("must not call LLM")))
    assert result.concepts_reviewed == 1
    assert result.findings == []


def test_review_bundle_garbage_reply_is_inconclusive(tmp_path):
    (tmp_path / "doc.md").write_text(_concept_md("A doc."), encoding="utf-8")
    result = okf_review.review_bundle(tmp_path, lambda p: "gibberish with no marker")
    assert result.inconclusive == 1
    assert result.findings[0].verdict == "INCONCLUSIVE"


def test_review_bundle_limit(tmp_path):
    _make_bundle(tmp_path)
    result = okf_review.review_bundle(tmp_path, lambda p: "VERDICT: PASS ok", limit=1)
    assert result.concepts_reviewed == 1


# --------------------------------------------------------------------------- #
# Report rendering                                                              #
# --------------------------------------------------------------------------- #
def test_render_report_disclaimer_and_sections():
    result = okf_review.ReviewResult(
        concepts_reviewed=2,
        findings=[
            okf_review.Finding("README", "description-drift", "PASS", "VERDICT: PASS fine"),
            okf_review.Finding("docs/arch", "index-drift", "FLAG", "VERDICT: FLAG stale row"),
            okf_review.Finding("docs/arch", "description-drift", "INCONCLUSIVE", "???"),
        ],
    )
    report = okf_review.render_report(result, datetime(2026, 7, 8, tzinfo=timezone.utc), "gemma")
    # The advisory disclaimer must lead the report.
    head = report.splitlines()[2]
    assert "AI-generated advisory output" in head and "human review" in head
    assert "🚩 1 flagged" in report
    assert "❓ 1 inconclusive" in report
    assert "## Flagged / inconclusive checks" in report
    assert "stale row" in report
    # Passing checks appear in the table but not in the detail section.
    assert report.count("`README`") == 1
