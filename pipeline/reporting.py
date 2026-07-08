"""JUnit-XML -> Markdown test report rendering for the pipeline."""

from __future__ import annotations

from pathlib import Path


def write_md_report(xml_path: Path, md_path: Path, generated) -> dict:
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
