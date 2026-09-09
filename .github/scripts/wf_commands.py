# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Escaping helpers for GitHub Actions workflow commands.

Workflow commands (``::warning file=...,title=...::message``) carry two
differently escaped parts. Shared by the step-summary renderer and the
coverage reporter so every emitted command follows the same rules.
"""


def escape_wf_data(value: object) -> str:
    """Escape the message body of a GitHub workflow command.

    Per GitHub's workflow-command rules, ``%``, ``CR`` and ``LF`` must
    be percent-encoded in the data (post-``::``) portion.
    """
    return str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_wf_property(value: object) -> str:
    """Escape a property value of a GitHub workflow command.

    Properties live in the comma-separated ``key=value`` list before
    ``::``. In addition to the data-escapes, ``,`` and ``:`` must be
    encoded so they cannot terminate the property list or the command
    prefix.
    """
    return escape_wf_data(value).replace(":", "%3A").replace(",", "%2C")
