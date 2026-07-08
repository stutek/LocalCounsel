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

    timestamp_str = generated.isoformat(timespec='seconds').replace('+00:00', 'Z')
    run_lines = [
        f"## Run on {timestamp_str} — {'✅ PASSED' if ok else '❌ FAILED'}",
        "",
        f"- **Totals:** {totals['tests']} tests · {passed} passed · "
        f"{totals['failures']} failed · {totals['errors']} errors · {totals['skipped']} skipped",
        f"- **Duration:** {totals['time']:.2f}s",
        "",
        "| Test | Outcome | Time |",
        "| --- | --- | --- |",
    ]
    run_lines += [f"| `{c['name']}` | {icon[c['outcome']]} {c['outcome']} | {c['time']:.2f}s |" for c in cases]

    failing = [c for c in cases if c["outcome"] in ("failed", "error")]
    if failing:
        run_lines += ["", "### Failures", ""]
        for c in failing:
            run_lines += [f"#### `{c['name']}`", "", "```", c["detail"] or "(no detail)", "```", ""]

    if any(c["sysout"] or c["syserr"] for c in cases):
        run_lines += ["", "### Captured output", ""]
        for c in cases:
            if not (c["sysout"] or c["syserr"]):
                continue
            run_lines += [f"<details><summary>{icon[c['outcome']]} <code>{c['name']}</code></summary>", ""]
            if c["sysout"]:
                run_lines += ["**stdout**", "", "```text", c["sysout"], "```", ""]
            if c["syserr"]:
                run_lines += ["**stderr**", "", "```text", c["syserr"], "```", ""]
            run_lines += ["</details>", ""]

    # 1. Standalone timestamped report
    standalone_lines = [
        "# LocalCounsel — Test Report",
        "",
        f"- **Generated:** {timestamp_str}",
    ] + run_lines[1:]
    md_path.write_text("\n".join(standalone_lines) + "\n", encoding="utf-8")

    # 2. Cumulative history report
    cumulative_path = md_path.parent / "test-report.md"
    header = "# LocalCounsel — Test Report History\n\n"
    existing_content = ""
    if cumulative_path.exists():
        try:
            content = cumulative_path.read_text(encoding="utf-8")
            if content.startswith(header):
                existing_content = content[len(header):]
            else:
                existing_content = content
        except OSError:
            pass

    new_cumulative_content = header + "\n".join(run_lines) + "\n\n" + existing_content
    cumulative_path.write_text(new_cumulative_content, encoding="utf-8")

    return {**totals, "passed": passed, "ok": ok}
