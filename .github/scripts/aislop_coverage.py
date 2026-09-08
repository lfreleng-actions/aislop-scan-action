# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Report reduced scan coverage separately from findings.

aislop emits a small set of diagnostics that record visibility loss,
an audit or analyzer that could not run, rather than a defect in the
scanned code. The dependency audit timing out against the npm registry
is the common case. Counting such a diagnostic as a finding turns a
registry outage into a failed pull request check that blames the
change, so this module partitions them out, renders them as a Coverage
section, and raises a job-level warning for each.

The set is an explicit list of rules. aislop's ``advisory`` score-impact
tier is not a usable key: it also holds ordinary style findings such as
``ai-slop/generic-naming``. The action's scan step counts notices
through this module's command line so the list lives in one place.

Usage as a script: ``aislop_coverage.py count REPORT`` prints the
number of coverage notices in the report.
"""

import json
import sys
from pathlib import Path
from typing import Any

from wf_commands import escape_wf_data, escape_wf_property

COVERAGE_RULES = frozenset(
    {
        "security/dependency-audit-skipped",
        "dotnet/projects-skipped",
        "cppcheck/chunks-skipped",
    }
)
WARNING_TITLE = "aislop: scan coverage degraded"
NOTE = (
    "coverage notice(s): part of the scan could not run, so the score may"
    " be inflated and a clean result is not conclusive. These describe the"
    " run (registry load, egress, missing tooling), not the code under"
    " review. Re-run once the underlying service recovers."
)
ENGINES_ROW = (
    "A required engine binary (ruff or golangci-lint) was missing, so"
    " that language was not scanned; see the engine provisioning step."
)

Finding = dict[str, Any]


def is_notice(diag: dict[str, Any]) -> bool:
    """Return True when a diagnostic records coverage loss, not a defect."""
    return diag.get("rule") in COVERAGE_RULES


def partition(diags: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Split normalised diagnostics into (findings, coverage notices)."""
    coverage = [d for d in diags if is_notice(d)]
    findings = [d for d in diags if not is_notice(d)]
    return findings, coverage


def detail(item: Finding) -> str:
    """Join a coverage notice's message and help into one line."""
    text = str(item["msg"] or item["rule"])
    if item["help"]:
        text = f"{text}: {item['help']}"
    return text.replace("\n", " ")


def render(coverage: list[Finding], engines_ready: bool) -> list[str]:
    """Render coverage notices as a markdown section; empty when none.

    A missing engine binary is the same kind of gap and gets a row of
    its own, so the section agrees with the action's coverage-degraded
    output whichever cause set it.
    """
    if not coverage and engines_ready:
        return []
    count = len(coverage) + (0 if engines_ready else 1)
    out = ["## Coverage \u26a0\ufe0f", "", f"{count} {NOTE}", ""]
    out.extend(["| Rule | Detail |", "| --- | --- |"])
    for item in coverage:
        cell = detail(item).replace("|", "\\|")
        out.append(f"| `{item['rule']}` | {cell} |")
    if not engines_ready:
        out.append(f"| `engines` | {ENGINES_ROW} |")
    out.append("")
    return out


def emit_warnings(coverage: list[Finding]) -> None:
    """Emit a job-level warning per coverage notice.

    No file location: these describe the run, not a line of the pull
    request, so they are emitted whether or not finding annotations
    are enabled. The engine provisioning step already warns about a
    missing binary, so that case is not repeated here.
    """
    title = escape_wf_property(WARNING_TITLE)
    for item in coverage:
        msg = f"{item['rule']}: {detail(item)}"
        print(f"::warning title={title}::{escape_wf_data(msg)}")


def count_notices(report_path: Path) -> int:
    """Count coverage notices in a raw aislop JSON report."""
    with report_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    diags = data.get("diagnostics") if isinstance(data, dict) else None
    if not isinstance(diags, list):
        return 0
    return sum(1 for d in diags if isinstance(d, dict) and is_notice(d))


def main(argv: list[str]) -> int:
    """Command-line entry point; see the module docstring."""
    if len(argv) != 3 or argv[1] != "count":
        print("usage: aislop_coverage.py count REPORT", file=sys.stderr)
        return 2
    print(count_notices(Path(argv[2])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
