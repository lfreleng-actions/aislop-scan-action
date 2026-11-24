# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation
"""Resolve the Ruff version to install for a scan."""

import argparse
import re
from pathlib import Path
from typing import Any

VERSION = r"[0-9]+\.[0-9]+\.[0-9]+"
GROUP_PIN = re.compile(
    rf"ruff\s*(?:==\s*({VERSION})|\(\s*==\s*({VERSION})\s*\))",
    re.IGNORECASE,
)


def read_toml(path: Path) -> dict[str, Any]:
    # Older Ruff releases classify tomllib as third-party by default.
    import tomllib

    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except FileNotFoundError:
        return {}


def unique_version(versions: set[str], source: str) -> str:
    if len(versions) > 1:
        raise ValueError(f"{source} has multiple Ruff versions; set ruff-version")
    return next(iter(versions), "")


def project_pin(root: Path) -> str:
    packages = read_toml(root / "uv.lock").get("package", [])
    if not isinstance(packages, list) or not all(
        isinstance(entry, dict) for entry in packages
    ):
        raise ValueError("uv.lock: expected [[package]] entries")
    locked = {
        entry["version"]
        for entry in packages
        if entry.get("name") == "ruff" and isinstance(entry.get("version"), str)
    }
    if locked:
        return unique_version(locked, "uv.lock")

    groups = read_toml(root / "pyproject.toml").get("dependency-groups", {})
    if not isinstance(groups, dict) or not all(
        isinstance(requirements, list) for requirements in groups.values()
    ):
        raise ValueError("pyproject.toml: expected dependency groups to be arrays")
    pinned: set[str] = set()
    for requirements in groups.values():
        for requirement in requirements:
            if not isinstance(requirement, str):
                continue
            specifier, separator, _ = requirement.partition(";")
            if match := GROUP_PIN.fullmatch(specifier.strip()):
                if separator:
                    raise ValueError(
                        "pyproject.toml dependency groups: exact Ruff pin has an "
                        "environment marker; set ruff-version to an explicit version"
                    )
                pinned.add(match[1] or match[2])
    return unique_version(pinned, "pyproject.toml dependency groups")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requested")
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    try:
        version = project_pin(args.root) if args.requested == "auto" else args.requested
        if (version or args.requested != "auto") and not re.fullmatch(VERSION, version):
            raise ValueError(
                "use an exact Ruff version (X.Y.Z), or set ruff-version to auto"
            )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(version)


if __name__ == "__main__":
    main()
