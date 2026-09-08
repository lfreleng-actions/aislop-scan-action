# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Report reduced scan coverage separately from findings.

aislop marks diagnostics that record visibility loss, an audit or
analyzer that could not run, with the ``advisory`` score-impact tier
(its own rationale: "not evidence of a vulnerability"). The dependency
audit timing out against the npm registry is the common case. Counting
such a diagnostic as a finding turns a registry outage into a failed
pull request check that blames the change, so this module partitions
them out, renders them as a Coverage section, and raises a job-level
warning for each. The action's scan step keys its
``coverage-degraded`` output off the same tier; keep the two in step.
"""

from typing import Any

from wf_commands import escape_wf_data, escape_wf_property

ADVISORY_TIER = "advisory"
WARNING_TITLE = "aislop: scan coverage degraded"
NOTE = (
    "coverage notice(s): part of the scan could not run, so the score may"
    " be inflated and a clean result is not conclusive. These describe the"
    " run (registry load, egress, missing tooling), not the code under"
    " review. Re-run once the underlying service recovers."
)

Finding = dict[str, Any]


def partition(diags: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Split normalised diagnostics into (findings, coverage notices)."""
    coverage = [d for d in diags if d.get("tier") == ADVISORY_TIER]
    findings = [d for d in diags if d.get("tier") != ADVISORY_TIER]
    return findings, coverage


def detail(item: Finding) -> str:
    """Join a coverage notice's message and help into one line."""
    text = str(item["msg"] or item["rule"])
    if item["help"]:
        text = f"{text}: {item['help']}"
    return text.replace("\n", " ")


def render(coverage: list[Finding]) -> list[str]:
    """Render coverage notices as a markdown section; empty when none."""
    if not coverage:
        return []
    out = ["## Coverage \u26a0\ufe0f", "", f"{len(coverage)} {NOTE}", ""]
    out.extend(["| Rule | Detail |", "| --- | --- |"])
    for item in coverage:
        cell = detail(item).replace("|", "\\|")
        out.append(f"| `{item['rule']}` | {cell} |")
    out.append("")
    return out


def emit_warnings(coverage: list[Finding]) -> None:
    """Emit a job-level warning per coverage notice.

    No file location: these describe the run, not a line of the pull
    request, so they are emitted whether or not finding annotations
    are enabled.
    """
    title = escape_wf_property(WARNING_TITLE)
    for item in coverage:
        msg = f"{item['rule']}: {detail(item)}"
        print(f"::warning title={title}::{escape_wf_data(msg)}")
