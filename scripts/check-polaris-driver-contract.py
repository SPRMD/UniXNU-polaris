#!/usr/bin/env python3
"""Validate the fail-closed Polaris hardware/driver contract.

The contract is evidence bookkeeping, not a driver loader.  It prevents a
candidate DT node or an Android userspace binary from silently becoming an
enabled Darwin driver.  ``--require-verified`` is used only by a future
hardware-validation job; the normal CI gate checks consistency and reports the
remaining candidates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "research" / "polaris-hardware-contract.json"
ALLOWED_STATUS = {"disabled", "candidate", "runtime-experimental", "verified"}
REQUIRED = {
    "power_keys", "display", "touch", "battery", "gpu", "wifi", "bluetooth",
    "nfc", "camera", "fingerprint",
}


def validate(data: dict[str, Any], *, require_verified: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    if data.get("schema") != 1:
        errors.append("schema must be 1")
    if data.get("board") != "xiaomi,polaris":
        errors.append("board must be xiaomi,polaris")
    if data.get("soc") != "SDM845":
        errors.append("soc must be SDM845")
    policy = data.get("policy", {})
    if policy.get("default_driver_mode") != "disabled-until-verified":
        errors.append("default_driver_mode must be disabled-until-verified")
    if policy.get("android_binaries_are_darwin_drivers") is not False:
        errors.append("Android binaries must never be treated as Darwin drivers")
    required_for_flash = policy.get("required_for_flash")
    if not isinstance(required_for_flash, list) or not required_for_flash:
        errors.append("required_for_flash must be a non-empty list")
        required_for_flash = []
    subsystems = data.get("subsystems")
    if not isinstance(subsystems, dict):
        errors.append("subsystems must be an object")
        subsystems = {}
    missing = sorted(REQUIRED - set(subsystems))
    extra = sorted(set(subsystems) - REQUIRED)
    errors.extend(f"missing subsystem: {name}" for name in missing)
    errors.extend(f"unknown subsystem: {name}" for name in extra)

    verified: list[str] = []
    enabled: list[str] = []
    for name in sorted(REQUIRED & set(subsystems)):
        item = subsystems[name]
        if not isinstance(item, dict):
            errors.append(f"{name}: entry must be an object")
            continue
        status = item.get("status")
        if status not in ALLOWED_STATUS:
            errors.append(f"{name}: invalid status {status!r}")
        if item.get("enabled") is not False and status != "verified":
            errors.append(f"{name}: candidate/disabled driver cannot be enabled")
        if item.get("enabled") is True:
            enabled.append(name)
        if status == "verified":
            verified.append(name)
            if not item.get("darwin_driver"):
                errors.append(f"{name}: verified entry needs darwin_driver")
            if not item.get("evidence"):
                errors.append(f"{name}: verified entry needs evidence")
        if item.get("darwin_driver") and item.get("source_type") == "android-binary":
            errors.append(f"{name}: Android binary cannot be a Darwin driver")

    if require_verified:
        errors.extend(f"{name}: not verified" for name in sorted(set(required_for_flash) - set(verified)))

    return {
        "schema": 1,
        "board": data.get("board"),
        "soc": data.get("soc"),
        "subsystem_count": len(subsystems),
        "verified": verified,
        "enabled": enabled,
        "all_subsystems_verified": not (REQUIRED - set(verified)),
        "required_for_flash": required_for_flash,
        "all_required_subsystems_verified": not (set(required_for_flash) - set(verified)),
        "errors": errors,
        "driver_loading_allowed": not errors and bool(verified),
        "device_access": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", nargs="?", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--require-verified", action="store_true")
    args = parser.parse_args()
    source = args.contract.resolve()
    if not source.is_file():
        parser.error(f"contract not found: {source}")
    report = validate(json.loads(source.read_text(encoding="utf-8")), require_verified=args.require_verified)
    rendered = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.output.resolve().write_text(rendered, encoding="utf-8")
    if report["errors"]:
        for error in report["errors"]:
            print(f"FAIL: {error}")
        raise SystemExit(1)
    print(f"PASS: Polaris driver contract is consistent; verified={len(report['verified'])}/{len(REQUIRED)}")
    print("No device access or MMIO was performed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
