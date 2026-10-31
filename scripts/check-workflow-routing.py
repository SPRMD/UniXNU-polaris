#!/usr/bin/env python3
"""Check that the Polaris build workflow is isolated from the legacy checks workflow.

This is intentionally a small text-level guard.  It does not try to parse YAML
with a library whose ``on`` key may be interpreted as a boolean; the assertions
are limited to the trigger blocks that this repository owns.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _trigger_block(text: str) -> str:
    """Return the top-level ``on:`` block up to the next top-level key."""
    match = re.search(r"(?m)^on:\s*\r?\n", text)
    if not match:
        raise ValueError("workflow has no top-level on: block")
    tail = text[match.end():]
    end = re.search(r"(?m)^[A-Za-z0-9_.-]+:\s*\r?$", tail)
    return tail[: end.start()] if end else tail


def validate(*, build_workflow: Path, legacy_workflow: Path) -> dict[str, object]:
    build = build_workflow.read_text(encoding="utf-8")
    legacy = legacy_workflow.read_text(encoding="utf-8")
    build_on = _trigger_block(build)
    legacy_on = _trigger_block(legacy)

    errors: list[str] = []
    if not re.search(r"(?m)^\s{2}push:\s*$", build_on):
        errors.append("polaris-build.yml must have a push trigger")
    if not re.search(r"(?m)^\s+- main\s*$", build_on):
        errors.append("polaris-build.yml push trigger must include main")
    if not re.search(r"(?m)^\s{2}workflow_dispatch:\s*$", build_on):
        errors.append("polaris-build.yml must have workflow_dispatch")
    if re.search(r"(?m)^\s{2}pull_request(?:_target)?:\s*$", build_on):
        errors.append("polaris-build.yml must not add a pull_request trigger")
    if re.search(r"(?m)^\s{2}push:\s*$", legacy_on):
        errors.append("legacy checks.yml must not have a push trigger")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "build_workflow": str(build_workflow),
        "legacy_workflow": str(legacy_workflow),
        "build_has_main_push": True,
        "build_has_manual_dispatch": True,
        "legacy_has_push": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-workflow", type=Path,
                        default=ROOT / ".github" / "workflows" / "polaris-build.yml")
    parser.add_argument("--legacy-workflow", type=Path,
                        default=ROOT / ".github" / "workflows" / "checks.yml")
    args = parser.parse_args()
    report = validate(build_workflow=args.build_workflow, legacy_workflow=args.legacy_workflow)
    print("PASS: Polaris workflow routing is isolated from checks.yml")
    for key, value in report.items():
        if key.endswith("workflow"):
            continue
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
