# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Tests for scripts/retry.sh.

The action's steps source this file and call ``retry_command`` around
the network work (``npm ci`` and the engine downloads). Each test runs
a bash snippet that sources it, as a step does, under
``set -euo pipefail``. The snippet replaces ``sleep`` with a function
that records the requested wait and advances bash's ``SECONDS`` clock,
so the tests are instant and can check the schedule exactly.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RETRY = ROOT / "scripts" / "retry.sh"

# Fixed waits unless a test asks for jitter, so schedules compare exactly.
NO_JITTER = {"RETRY_JITTER_PCT": "0"}

PRELUDE = """\
set -euo pipefail
. "${RETRY_SH}"
sleep() { echo "$1" >> "${SLEEP_LOG}"; SECONDS=$((SECONDS + $1)); }
attempts=0
count() { attempts=$((attempts + 1)); }
"""


def run(
    tmp_path: Path, body: str, **env: str
) -> tuple[subprocess.CompletedProcess[str], list[int]]:
    """Run ``body`` after the prelude; return the process and the waits."""
    log = tmp_path / "sleeps"
    log.touch()
    clean = {k: v for k, v in os.environ.items() if not k.startswith("RETRY_")}
    clean.update({"RETRY_SH": str(RETRY), "SLEEP_LOG": str(log), **env})
    proc = subprocess.run(  # noqa: S603
        ["bash", "-c", PRELUDE + body],  # noqa: S607
        capture_output=True,
        text=True,
        env=clean,
        check=False,
    )
    waits = [int(line) for line in log.read_text().split()]
    return proc, waits


def test_success_on_the_first_attempt_never_waits(tmp_path: Path) -> None:
    proc, waits = run(tmp_path, "retry_command 'step' true\necho done")
    assert proc.returncode == 0, proc.stderr
    assert "done" in proc.stdout
    assert waits == []


def test_retries_until_the_command_succeeds(tmp_path: Path) -> None:
    body = """\
flaky() { count; [ "${attempts}" -ge 3 ]; }
retry_command 'step' flaky
echo "attempts=${attempts}"
"""
    proc, waits = run(tmp_path, body, **NO_JITTER)
    assert proc.returncode == 0, proc.stderr
    assert "attempts=3" in proc.stdout
    assert waits == [10, 20]


def test_default_schedule_is_four_retries_doubling_from_ten(tmp_path: Path) -> None:
    body = """\
down() { count; return 7; }
rc=0
retry_command 'step' down || rc=$?
echo "attempts=${attempts} rc=${rc}"
"""
    proc, waits = run(tmp_path, body, **NO_JITTER)
    assert proc.returncode == 0, proc.stderr
    assert "attempts=5 rc=7" in proc.stdout
    assert waits == [10, 20, 40, 80]


def test_the_time_budget_stops_the_retries_early(tmp_path: Path) -> None:
    # Each attempt takes 60 s: 60 + 10 + 60 + 20 + 60 leaves 170 s, and
    # the next 40 s wait would pass the 180 s budget.
    body = """\
slow() { count; SECONDS=$((SECONDS + 60)); return 1; }
rc=0
retry_command 'step' slow || rc=$?
echo "attempts=${attempts} rc=${rc}"
"""
    proc, waits = run(tmp_path, body, **NO_JITTER)
    assert "attempts=3 rc=1" in proc.stdout, proc.stderr
    assert waits == [10, 20]


def test_jitter_only_ever_shortens_a_wait(tmp_path: Path) -> None:
    body = """\
down() { return 1; }
retry_command 'step' down || true
"""
    for i in range(20):
        # A fresh directory each time: the sleep log accumulates per run.
        sub = tmp_path / f"run{i}"
        sub.mkdir()
        proc, waits = run(sub, body)
        assert proc.returncode == 0, proc.stderr
        assert len(waits) == 4
        for wait, nominal in zip(waits, (10, 20, 40, 80), strict=True):
            assert 0.75 * nominal <= wait <= nominal


def test_the_schedule_can_be_tuned_by_environment(tmp_path: Path) -> None:
    body = """\
down() { count; return 1; }
retry_command 'step' down || true
echo "attempts=${attempts}"
"""
    proc, waits = run(tmp_path, body, RETRY_MAX="2", RETRY_BASE_DELAY="5", **NO_JITTER)
    assert "attempts=3" in proc.stdout
    assert waits == [5, 10]


def test_failure_reports_the_commands_own_exit_status(tmp_path: Path) -> None:
    proc, _ = run(tmp_path, "retry_command 'step' sh -c 'exit 42'", **NO_JITTER)
    assert proc.returncode == 42


def test_a_notice_names_the_step_and_the_exit_status(tmp_path: Path) -> None:
    body = """\
flaky() { count; echo out-from-command; [ "${attempts}" -ge 2 ]; }
retry_command 'npm ci' flaky
"""
    proc, _ = run(tmp_path, body, **NO_JITTER)
    assert "npm ci" in proc.stderr
    assert "retry 1 of 4" in proc.stderr
    assert proc.stdout.count("out-from-command") == 2


def test_arguments_reach_the_command_intact(tmp_path: Path) -> None:
    body = """\
show() { printf '[%s]' "$@"; echo; }
retry_command 'step' show 'two words' "a'b" ''
"""
    proc, _ = run(tmp_path, body)
    assert proc.stdout.strip() == "[two words][a'b][]"
