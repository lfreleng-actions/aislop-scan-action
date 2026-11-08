# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Defective on purpose: golden-test input, never shipped or imported."""


def total(items):
    result=0
    for i in range(len(items)):
        result+=items[i]
    return result
