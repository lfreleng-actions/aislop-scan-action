# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Convert an aislop JSON report into SARIF 2.1.0.

aislop writes one output format per run, so the action runs it once
with JSON (the richer format: it carries the score, coverage and
per-diagnostic help) and derives the SARIF from that report here. One
scan cannot disagree with itself, which two scans of the same tree can:
a dependency audit that times out in only one of them adds or drops a
finding.

The output mirrors aislop's own ``--sarif`` writer for the same scan;
``tests/test_aislop_sarif.py`` holds it to that by comparing both on
fixture trees with the pinned aislop.

Usage as a script: ``aislop_sarif.py REPORT OUT``. A report that cannot
be read or does not carry the fields the mapping needs exits non-zero
with an error naming the problem, and leaves no output file behind.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/"
    "Schemata/sarif-schema-2.1.0.json"
)
SARIF_VERSION = "2.1.0"
INFORMATION_URI = "https://github.com/scanaislop/aislop"
LEVELS = {"error": "error", "warning": "warning"}
REQUIRED_STRINGS = ("rule", "filePath", "message")

Diagnostic = dict[str, Any]


class ReportError(ValueError):
    """The report cannot be converted; the message names the problem."""


def _one_based(diag: Diagnostic, index: int, key: str) -> int:
    """Return a 1-based position; aislop uses 0 for whole-file/unknown."""
    value = diag.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReportError(f"diagnostic {index}: '{key}' is not an integer")
    return max(value, 1)


def _check_diagnostic(diag: object, index: int) -> Diagnostic:
    """Return the diagnostic when it carries the fields SARIF needs."""
    if not isinstance(diag, dict):
        raise ReportError(f"diagnostic {index} is not an object")
    for key in REQUIRED_STRINGS:
        if not isinstance(diag.get(key), str):
            raise ReportError(f"diagnostic {index} is missing string '{key}'")
    return diag


def _rule(diag: Diagnostic) -> dict[str, Any]:
    """Describe a rule from the first diagnostic that raised it."""
    return {
        "id": diag["rule"],
        "name": diag["rule"],
        "shortDescription": {"text": diag["message"]},
        "help": {"text": diag.get("help") or diag["message"]},
    }


def _result(diag: Diagnostic, index: int, rule_index: int) -> dict[str, Any]:
    """Build the SARIF result for one diagnostic."""
    result: dict[str, Any] = {
        "ruleId": diag["rule"],
        "ruleIndex": rule_index,
        "level": LEVELS.get(str(diag.get("severity")), "note"),
        "message": {"text": diag["message"]},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": diag["filePath"].replace(os.sep, "/")},
                    "region": {
                        "startLine": _one_based(diag, index, "line"),
                        "startColumn": _one_based(diag, index, "column"),
                    },
                }
            }
        ],
    }
    # Set in changes mode: whether the finding sits on a changed line.
    if diag.get("changeContext"):
        result["properties"] = {"changeContext": diag["changeContext"]}
    return result


def to_sarif(report: object) -> dict[str, Any]:
    """Return the SARIF log for a parsed aislop JSON report.

    Every diagnostic becomes a result, coverage notices included, in
    report order; callers decide what to count.
    """
    if not isinstance(report, dict):
        raise ReportError("report is not a JSON object")
    version = report.get("cliVersion")
    if not isinstance(version, str) or not version:
        raise ReportError("report is missing string 'cliVersion'")
    raw = report.get("diagnostics")
    if not isinstance(raw, list):
        raise ReportError("report 'diagnostics' is not a list")
    diags = [_check_diagnostic(d, i) for i, d in enumerate(raw)]
    rules: list[dict[str, Any]] = []
    indices: dict[str, int] = {}
    for diag in diags:
        if diag["rule"] not in indices:
            indices[diag["rule"]] = len(rules)
            rules.append(_rule(diag))
    results = [_result(d, i, indices[d["rule"]]) for i, d in enumerate(diags)]
    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "aislop",
                        "version": version,
                        "informationUri": INFORMATION_URI,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def load_report(path: Path) -> object:
    """Parse the JSON report at path, naming the file on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot read report {path}: {exc}") from exc


def write_atomic(path: Path, text: str) -> None:
    """Write text to path whole or not at all."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str]) -> int:
    """Convert REPORT to SARIF at OUT; return the process exit code."""
    if len(argv) != 2:
        print("usage: aislop_sarif.py REPORT OUT", file=sys.stderr)
        return 2
    report_path, out_path = Path(argv[0]), Path(argv[1])
    try:
        sarif = to_sarif(load_report(report_path))
        write_atomic(out_path, json.dumps(sarif, indent=2) + "\n")
    except ReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: cannot write SARIF {out_path}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
