# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Tests for the aislop JSON to SARIF converter.

The golden tests run the pinned aislop over each fixture tree twice,
once for JSON and once for SARIF, and require the converted JSON to
equal aislop's own SARIF. They find aislop through ``AISLOP_BIN`` or
the PATH and skip when neither provides the version package.json
pins; with ``AISLOP_BIN`` set, a missing binary or another version
fails instead, so CI cannot pass by skipping.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import aislop_sarif
import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_NAMES = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())
SCRIPT = ROOT / "scripts" / "aislop_sarif.py"
PINNED = json.loads((ROOT / "package.json").read_text())["dependencies"]["aislop"]
ENV = {**os.environ, "AISLOP_NO_TELEMETRY": "1", "AISLOP_NO_HISTORY": "1"}
GIT = [
    "git",
    "-c",
    "user.name=fixture",
    "-c",
    "user.email=fixture@example.invalid",
    "-c",
    "commit.gpgsign=false",
]


def _version(binary: str) -> str:
    """Return the version an aislop binary reports."""
    out = subprocess.run([binary, "-V"], capture_output=True, text=True, check=True)
    return out.stdout.strip()


@pytest.fixture(scope="session")
def aislop() -> str:
    """Path to the pinned aislop binary, or skip the golden tests."""
    explicit = os.environ.get("AISLOP_BIN")
    if explicit:
        if not os.access(explicit, os.X_OK):
            pytest.fail(f"AISLOP_BIN={explicit} is not an executable file")
        found = _version(explicit)
        if found != PINNED:
            pytest.fail(f"AISLOP_BIN is aislop {found}; package.json pins {PINNED}")
        return explicit
    binary = shutil.which("aislop") or ""
    if not binary:
        pytest.skip("aislop is not installed; set AISLOP_BIN to run the golden tests")
    found = _version(binary)
    if found != PINNED:
        pytest.skip(f"aislop on PATH is {found}; the golden tests need {PINNED}")
    return binary


def _scan(aislop: str, tree: Path, *args: str) -> Any:
    """Run ``aislop ci`` in tree and parse its stdout."""
    out = subprocess.run(
        [aislop, "ci", *args],
        cwd=tree,
        env=ENV,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.stdout, f"aislop ci {' '.join(args)} wrote nothing: {out.stderr}"
    return json.loads(out.stdout)


def _golden(aislop: str, tree: Path, *args: str) -> dict[str, Any]:
    """Assert the converter reproduces aislop's SARIF; return the report."""
    report = _scan(aislop, tree, *args, "--format", "json")
    expected = _scan(aislop, tree, *args, "--sarif")
    assert aislop_sarif.to_sarif(report) == expected
    return report


def _copy_fixture(name: str, dest: Path) -> Path:
    """Copy one fixture tree out of the repository, so its git and
    aislop configuration cannot reach the scan."""
    tree = dest / name
    shutil.copytree(FIXTURES / name, tree)
    return tree


@pytest.fixture(scope="module")
def reports(aislop: str, tmp_path_factory: pytest.TempPathFactory) -> list[Any]:
    """Golden-check every fixture in full mode and return the reports."""
    found = []
    for name in FIXTURE_NAMES:
        tree = _copy_fixture(name, tmp_path_factory.mktemp("full"))
        found.append(_golden(aislop, tree))
    return found


def test_golden_full_scan(reports: list[Any]) -> None:
    """Each fixture converts to exactly aislop's own SARIF."""
    assert len(reports) == len(FIXTURE_NAMES)


def test_fixtures_cover_the_mapping(reports: list[Any]) -> None:
    """The fixtures exercise every branch of the mapping between them.

    Without the engine binaries aislop reports far less, and the golden
    test would compare two near-empty logs; this guards against that.
    """
    diags = [d for r in reports for d in r["diagnostics"]]
    rules = [d["rule"] for d in diags]
    severities = {d["severity"] for d in diags}
    checks = {
        "every severity": {"error", "warning", "info"} <= severities,
        "a diagnostic with help": any(d["help"] for d in diags),
        "a diagnostic without help": any(not d["help"] for d in diags),
        "a whole-file finding (line 0)": any(d["line"] == 0 for d in diags),
        "a finding at column 0": any(d["column"] == 0 for d in diags),
        "repeated findings of one rule": len(set(rules)) < len(rules),
    }
    missing = [name for name, ok in checks.items() if not ok]
    assert not missing, (
        f"fixtures lack {missing}; are the engine binaries (aislop-tools) installed?"
    )


def test_golden_changes_scan(aislop: str, tmp_path: Path) -> None:
    """Changes mode adds a change context, which SARIF carries too."""
    tree = _copy_fixture(FIXTURE_NAMES[0], tmp_path)
    subprocess.run([*GIT, "init", "-q"], cwd=tree, check=True)
    subprocess.run([*GIT, "add", "."], cwd=tree, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "base"], cwd=tree, check=True)
    for path in tree.rglob("*.py"):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n\ndef added(data):\n    try:\n        return data()\n    except:\n        pass\n"
            )
    report = _golden(aislop, tree, "--changes")
    contexts = {d.get("changeContext") for d in report["diagnostics"]}
    assert {"changed-line", "existing-file-context"} <= contexts


def _report(*diags: object) -> dict[str, Any]:
    return {"cliVersion": "1.2.3", "diagnostics": list(diags)}


DIAG = {
    "rule": "r/one",
    "filePath": "a.py",
    "message": "m",
    "help": "",
    "severity": "info",
    "line": 0,
    "column": 0,
}


def test_mapping_of_one_diagnostic() -> None:
    """Hand-written check of the mapping, independent of aislop."""
    sarif = aislop_sarif.to_sarif(_report(DIAG))
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["version"] == "1.2.3"
    assert run["tool"]["driver"]["rules"] == [
        {
            "id": "r/one",
            "name": "r/one",
            "shortDescription": {"text": "m"},
            "help": {"text": "m"},
        }
    ]
    (result,) = run["results"]
    assert result["level"] == "note"
    assert result["locations"][0]["physicalLocation"]["region"] == {
        "startLine": 1,
        "startColumn": 1,
    }
    assert "properties" not in result


@pytest.mark.parametrize(
    ("report", "problem"),
    [
        ([], "not a JSON object"),
        ({"diagnostics": []}, "cliVersion"),
        ({"cliVersion": "1", "diagnostics": {}}, "'diagnostics' is not a list"),
        ({"cliVersion": "1"}, "'diagnostics' is not a list"),
        (_report("x"), "diagnostic 0 is not an object"),
        (_report({**DIAG, "rule": None}), "diagnostic 0 is missing string 'rule'"),
        (
            _report(DIAG, {k: v for k, v in DIAG.items() if k != "filePath"}),
            "diagnostic 1 is missing string 'filePath'",
        ),
        (
            _report({k: v for k, v in DIAG.items() if k != "message"}),
            "diagnostic 0 is missing string 'message'",
        ),
        (_report({**DIAG, "line": "3"}), "diagnostic 0: 'line' is not an integer"),
    ],
)
def test_malformed_report_is_rejected(report: Any, problem: str) -> None:
    """A report the mapping cannot use raises an error naming why."""
    with pytest.raises(aislop_sarif.ReportError, match=problem):
        aislop_sarif.to_sarif(report)


def _cli(
    report_text: str, tmp_path: Path
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the converter script on report_text; return it and the OUT path."""
    report = tmp_path / "report.json"
    report.write_text(report_text, encoding="utf-8")
    out = tmp_path / "out.sarif"
    proc = subprocess.run(
        ["python3", str(SCRIPT), str(report), str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, out


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("{not json", "cannot read report"),
        (json.dumps(_report({**DIAG, "filePath": 7})), "missing string 'filePath'"),
    ],
)
def test_cli_fails_without_writing(text: str, problem: str, tmp_path: Path) -> None:
    """A bad report exits non-zero, names the problem, writes nothing."""
    proc, out = _cli(text, tmp_path)
    assert proc.returncode == 1
    assert problem in proc.stderr
    assert not out.exists()
    assert [p.name for p in tmp_path.iterdir()] == ["report.json"]


def test_cli_missing_report(tmp_path: Path) -> None:
    """An unreadable report path fails the same way."""
    out = tmp_path / "out.sarif"
    proc = subprocess.run(
        ["python3", str(SCRIPT), str(tmp_path / "absent.json"), str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "cannot read report" in proc.stderr
    assert not out.exists()


def test_cli_writes_sarif(tmp_path: Path) -> None:
    """A good report converts to a parseable SARIF file."""
    proc, out = _cli(json.dumps(_report(DIAG)), tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(out.read_text())["version"] == "2.1.0"
