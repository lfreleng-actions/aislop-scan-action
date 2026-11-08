# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Defective on purpose: golden-test input, never shipped or imported."""

import os
import sys


def handler(data):
    try:
        return int(data)
    except:
        pass


def helper(data):
    try:
        return float(data)
    except:
        return None
