# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Tests for the retrying steps of action.yaml.

Two steps do network work: ``Install aislop`` (``npm ci``) and
``Provision engine binaries`` (``aislop-tools``, which downloads ruff
and golangci-lint from GitHub release assets). Each test extracts the
step's script from action.yaml, so it runs the code the action runs,
and executes it the way the runner does, with stub ``npm`` and
``aislop-tools`` programs that fail a set number of times. The retry
waits are set to zero, so the tests do not sleep.
"""

import re
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ACTION = ROOT / "action.yaml"

NO_WAIT = {"RETRY_BASE_DELAY": "0", "RETRY_JITTER_PCT": "0"}


def step_script(name: str) -> str:
    """Return the ``run`` script of the named step in action.yaml."""
    lines = ACTION.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if f"- name: '{name}'" in line)
    run = next(
        i for i in range(start, len(lines)) if re.match(r"^\s+run: \|", lines[i])
    )
    indent = len(lines[run]) - len(lines[run].lstrip())
    body: list[str] = []
    for line in lines[run + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)) + "\n"


def write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def run_step(
    tmp_path: Path, name: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "step.sh"
    script.write_text(step_script(name))
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    full = {
        # System tools only: a ruff or golangci-lint elsewhere on the
        # PATH would count as a system installation.
        "PATH": f"{stubs}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "github_output"),
        "RUNNER_TEMP": str(tmp_path),
        "ACTION_PATH": str(ROOT),
        **NO_WAIT,
        **env,
    }
    return subprocess.run(  # noqa: S603
        ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", str(script)],
        capture_output=True,
        text=True,
        env=full,
        cwd=tmp_path,
        check=False,
    )


def outputs(tmp_path: Path) -> dict[str, str]:
    path = tmp_path / "github_output"
    result: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep:
                result[key] = value
    return result


def step_env_names(name: str) -> set[str]:
    """Return the variable names a step declares in its ``env`` block."""
    lines = ACTION.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if f"- name: '{name}'" in line)
    names: set[str] = set()
    in_env = False
    for line in lines[start + 1 :]:
        if re.match(r"^    - ", line):
            break
        if re.match(r"^      env:\s*$", line):
            in_env = True
        elif in_env:
            match = re.match(r"^        ([A-Z_]+):", line)
            if match is None:
                in_env = False
            else:
                names.add(match.group(1))
    return names


@pytest.mark.parametrize("name", ["Install aislop", "Provision engine binaries"])
def test_steps_that_source_the_helper_declare_the_action_path(name: str) -> None:
    # The harness above supplies ACTION_PATH, so it would hide a step
    # that forgot to declare it; the runner supplies only what env lists.
    assert "retry.sh" in step_script(name)
    assert "ACTION_PATH" in step_env_names(name)


# --- Install aislop ------------------------------------------------------

NPM_STUB = """\
#!/bin/sh
state="${STUB_STATE}/npm-runs"
runs=$(cat "${state}" 2>/dev/null || echo 0)
runs=$((runs + 1))
echo "${runs}" > "${state}"
if [ "${runs}" -le "${NPM_FAILURES}" ]; then
  echo "npm error code E504" >&2
  exit 1
fi
mkdir -p node_modules/.bin
printf '#!/bin/sh\\necho 0.20.0\\n' > node_modules/.bin/aislop
chmod +x node_modules/.bin/aislop
"""


def run_install(tmp_path: Path, failures: int) -> subprocess.CompletedProcess[str]:
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    write_executable(tmp_path / "stubs" / "npm", NPM_STUB)
    return run_step(
        tmp_path,
        "Install aislop",
        {
            "STUB_STATE": str(state),
            "NPM_FAILURES": str(failures),
            "VERSION": "0.20.0",
            "LOCKED": "true",
        },
    )


def npm_runs(tmp_path: Path) -> int:
    return int((tmp_path / "state" / "npm-runs").read_text())


def test_install_runs_npm_once_when_the_registry_answers(tmp_path: Path) -> None:
    proc = run_install(tmp_path, failures=0)
    assert proc.returncode == 0, proc.stderr
    assert npm_runs(tmp_path) == 1
    assert outputs(tmp_path)["aislop"].endswith("node_modules/.bin/aislop")


def test_install_retries_a_registry_outage(tmp_path: Path) -> None:
    proc = run_install(tmp_path, failures=3)
    assert proc.returncode == 0, proc.stderr
    assert npm_runs(tmp_path) == 4
    assert outputs(tmp_path)["aislop"].endswith("node_modules/.bin/aislop")


def test_install_gives_up_after_four_retries(tmp_path: Path) -> None:
    proc = run_install(tmp_path, failures=99)
    assert proc.returncode != 0
    assert npm_runs(tmp_path) == 5


def test_install_retries_the_unlocked_install_too(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    write_executable(tmp_path / "stubs" / "npm", NPM_STUB)
    proc = run_step(
        tmp_path,
        "Install aislop",
        {
            "STUB_STATE": str(state),
            "NPM_FAILURES": "2",
            "VERSION": "0.20.0",
            "LOCKED": "false",
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert npm_runs(tmp_path) == 3


# --- Provision engine binaries ------------------------------------------

TOOLS_STUB = """\
#!/bin/sh
state="${STUB_STATE}/tools-runs"
runs=$(cat "${state}" 2>/dev/null || echo 0)
runs=$((runs + 1))
echo "${runs}" > "${state}"
if [ "${runs}" -ge "${TOOLS_WORK_FROM}" ]; then
  bin="${WORKDIR}/node_modules/aislop/tools/bin"
  mkdir -p "${bin}"
  for tool in ruff golangci-lint; do
    printf '#!/bin/sh\\n' > "${bin}/${tool}"
    chmod +x "${bin}/${tool}"
  done
fi
exit "${TOOLS_EXIT}"
"""


def run_engines(
    tmp_path: Path, work_from: int, require: str = "true", exit_code: int = 1
) -> subprocess.CompletedProcess[str]:
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    workdir = tmp_path / "work"
    write_executable(workdir / "node_modules" / ".bin" / "aislop-tools", TOOLS_STUB)
    return run_step(
        tmp_path,
        "Provision engine binaries",
        {
            "STUB_STATE": str(state),
            "WORKDIR": str(workdir),
            "REQUIRE": require,
            "TOOLS_WORK_FROM": str(work_from),
            "TOOLS_EXIT": str(exit_code),
            "AISLOP_NO_TELEMETRY": "1",
        },
    )


def tools_runs(tmp_path: Path) -> int:
    return int((tmp_path / "state" / "tools-runs").read_text())


def test_engines_run_the_installer_once_when_it_succeeds(tmp_path: Path) -> None:
    proc = run_engines(tmp_path, work_from=1, exit_code=0)
    assert proc.returncode == 0, proc.stderr
    assert tools_runs(tmp_path) == 1
    assert outputs(tmp_path)["ready"] == "true"


def test_a_nonzero_exit_with_both_binaries_present_is_not_retried(
    tmp_path: Path,
) -> None:
    # aislop-tools exits non-zero when an optional .NET analyzer fails to
    # download even though ruff and golangci-lint installed: the outcome,
    # not the exit status, decides.
    proc = run_engines(tmp_path, work_from=1, exit_code=1)
    assert proc.returncode == 0, proc.stderr
    assert tools_runs(tmp_path) == 1
    assert outputs(tmp_path)["ready"] == "true"


def test_engines_retry_until_the_binaries_arrive(tmp_path: Path) -> None:
    proc = run_engines(tmp_path, work_from=4)
    assert proc.returncode == 0, proc.stderr
    assert tools_runs(tmp_path) == 4
    assert outputs(tmp_path)["ready"] == "true"


def test_engines_give_up_after_four_retries_and_fail_when_required(
    tmp_path: Path,
) -> None:
    proc = run_engines(tmp_path, work_from=99, require="true")
    assert proc.returncode == 1
    assert tools_runs(tmp_path) == 5
    assert "engine binaries missing" in proc.stdout
    assert outputs(tmp_path)["ready"] == "false"


def test_engines_give_up_after_four_retries_and_warn_when_optional(
    tmp_path: Path,
) -> None:
    proc = run_engines(tmp_path, work_from=99, require="false")
    assert proc.returncode == 0, proc.stderr
    assert tools_runs(tmp_path) == 5
    assert "::warning::" in proc.stdout
    assert outputs(tmp_path)["ready"] == "false"


def test_engines_report_only_the_languages_actually_missing(tmp_path: Path) -> None:
    # Only ruff arrives: the note names golangci-lint and Go, not Python.
    state = tmp_path / "state"
    state.mkdir()
    workdir = tmp_path / "work"
    stub = TOOLS_STUB.replace("golangci-lint ", "").replace(
        "ruff golangci-lint", "ruff"
    )
    write_executable(workdir / "node_modules" / ".bin" / "aislop-tools", stub)
    proc = run_step(
        tmp_path,
        "Provision engine binaries",
        {
            "STUB_STATE": str(state),
            "WORKDIR": str(workdir),
            "REQUIRE": "false",
            "TOOLS_WORK_FROM": "1",
            "TOOLS_EXIT": "0",
            "AISLOP_NO_TELEMETRY": "1",
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert "missing: golangci-lint. Go findings" in proc.stdout
    assert "Python" not in proc.stdout.split("missing:")[1]
