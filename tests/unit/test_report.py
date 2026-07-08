"""Unit tests for pipeline.reporting.write_md_report — pure JUnit-XML -> Markdown."""

from __future__ import annotations

from datetime import datetime, timezone

from pipeline import reporting

# One pass, one failure — the smallest JUnit XML that exercises totals + the
# failure-rendering branch.
_JUNIT_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="2" failures="1" errors="0" skipped="0" time="0.50">
  <testcase classname="tests.test_demo" name="test_pass" time="0.10"></testcase>
  <testcase classname="tests.test_demo" name="test_fail" time="0.40">
    <failure message="AssertionError: kaboom in the widget">assert 1 == 2</failure>
  </testcase>
</testsuite>
"""


def test_write_md_report_totals_and_failure_section(tmp_path):
    xml_path = tmp_path / "junit.xml"
    xml_path.write_text(_JUNIT_XML, encoding="utf-8")
    md_path = tmp_path / "report.md"

    totals = reporting.write_md_report(
        xml_path, md_path, datetime(2026, 7, 8, tzinfo=timezone.utc)
    )

    assert totals["tests"] == 2
    assert totals["failures"] == 1
    assert totals["errors"] == 0
    assert totals["skipped"] == 0
    assert totals["passed"] == 1
    assert totals["ok"] is False

    content = md_path.read_text(encoding="utf-8")
    assert "### Failures" in content
    assert "test_fail" in content
    assert "kaboom in the widget" in content

    # Test cumulative history report
    cumulative_path = tmp_path / "test-report.md"
    assert cumulative_path.exists()
    cumulative_content = cumulative_path.read_text(encoding="utf-8")
    assert "# LocalCounsel — Test Report History" in cumulative_content
    assert "## Run on 2026-07-08T00:00:00Z" in cumulative_content

    # Run again with a new timestamp to test appending/prepended history
    reporting.write_md_report(
        xml_path, md_path, datetime(2026, 7, 9, tzinfo=timezone.utc)
    )
    updated_cumulative = cumulative_path.read_text(encoding="utf-8")
    assert "## Run on 2026-07-09T00:00:00Z" in updated_cumulative
    # The newer run should be prepended before the older run
    pos_9 = updated_cumulative.find("2026-07-09T00:00:00Z")
    pos_8 = updated_cumulative.find("2026-07-08T00:00:00Z")
    assert pos_9 < pos_8
