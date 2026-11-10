# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
#
# shellcheck shell=bash
#
# Retry helper for the network steps of action.yaml. A step sources this
# file, then calls:
#
#   retry_command <label> <command> [<argument>...]
#
# The command runs until it succeeds or the schedule is spent. The default
# schedule is four retries, waiting 10, 20, 40 and 80 seconds, with each
# wait cut by up to a quarter at random so parallel jobs do not retry in
# step. The helper also stops retrying when the next wait would take the
# whole call past 180 seconds. On failure it returns the command's own
# exit status. It prints a notice to stderr before each wait.
#
# The schedule comes from the environment, which exists so the tests can
# run it without waiting:
#
#   RETRY_MAX          retries after the first attempt (default 4)
#   RETRY_BASE_DELAY   seconds before the first retry (default 10)
#   RETRY_BUDGET       seconds of retrying allowed (default 180)
#   RETRY_JITTER_PCT   percentage a wait may be cut by (default 25)
#
# The helper retries every non-zero exit, so only wrap a command that is
# safe to repeat and fails for reasons a later attempt can fix.

retry_command() {
  local label="$1"
  shift
  local retries="${RETRY_MAX:-4}"
  local base="${RETRY_BASE_DELAY:-10}"
  local budget="${RETRY_BUDGET:-180}"
  local jitter="${RETRY_JITTER_PCT:-25}"
  local start="${SECONDS}"
  local attempt=0 rc nominal delay
  while true; do
    attempt=$((attempt + 1))
    rc=0
    "$@" || rc=$?
    if [ "${rc}" -eq 0 ]; then
      return 0
    fi
    if [ "${attempt}" -gt "${retries}" ]; then
      return "${rc}"
    fi
    nominal=$((base * (1 << (attempt - 1))))
    delay=$((nominal - RANDOM % (nominal * jitter / 100 + 1)))
    if [ $((SECONDS - start + delay)) -gt "${budget}" ]; then
      return "${rc}"
    fi
    echo "${label}: exit status ${rc}; retry ${attempt} of ${retries}" \
      "in ${delay}s" >&2
    sleep "${delay}"
  done
}
