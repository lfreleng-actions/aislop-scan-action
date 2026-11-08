<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 The Linux Foundation
-->

# SARIF golden-test fixtures

Test data: nothing here ships or runs as part of the action. Each
directory is a small source tree that is defective on purpose, so that
aislop reports findings against it. `tests/test_aislop_sarif.py` copies
each tree out of the repository, scans it with the pinned aislop in
both JSON and SARIF form, and requires `scripts/aislop_sarif.py` to
turn the JSON into the SARIF aislop wrote, field for field.

Between them the trees produce error, warning and info diagnostics,
diagnostics with and without `help` text, a whole-file finding
(line 0), a finding at column 0 and repeated findings of one rule. The
test asserts that coverage, so a fixture edit that loses one fails.

`.aislopignore` and `.ruff.toml` exclude this directory from the
repository's own scans. Do not fix the findings here.
