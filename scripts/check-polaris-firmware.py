#!/usr/bin/env python3
"""Check Polaris firmware metadata without loading or shipping blobs.

The UniXNU Polaris repository deliberately does not contain Qualcomm or
camera firmware. This checker validates the reviewable contract and, when a
caller supplies a private directory, records exact file size/hash matches.
Normal CI runs without ``--firmware-dir`` and therefore produces an explicit
``available=false`` report instead of pretending that firmware is present.
No device, adb, fastboot, network, or MMIO access is performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "research" / "polaris-firmware-contract.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_contract(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema") != 1:
        errors.append("schema must be 1")
    if data.get("board") != "xiaomi,polaris":
        errors.append("board must be xiaomi,polaris")
    if data.get("soc") != "SDM845":
        errors.append("soc must be SDM845")
    policy = data.get("policy")
    if not isinstance(policy, dict):
        errors.append("policy must be an object")
    else:
        for key in ("binary_blobs_tracked", "android_vendor_blobs_are_darwin_drivers"):
            if policy.get(key) is not False:
                errors.append(f"policy.{key} must be false")
        if policy.get("default_load_mode") != "metadata-only":
            errors.append("policy.default_load_mode must be metadata-only")
        if policy.get("require_sha256_before_use") is not True:
            errors.append("policy.require_sha256_before_use must be true")
    families = data.get("families")
    if not isinstance(families, list) or not families:
        errors.append("families must be a non-empty list")
    else:
        ids: set[str] = set()
        for item in families:
            if not isinstance(item, dict):
                errors.append("family entries must be objects")
                continue
            ident = item.get("id")
            if not isinstance(ident, str) or not ident:
                errors.append("family id must be a non-empty string")
            elif ident in ids:
                errors.append(f"duplicate family id: {ident}")
            else:
                ids.add(ident)
            if item.get("darwin_compatible") is not False:
                errors.append(f"{ident}: darwin_compatible must be false until tested")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("artifacts must be a list")
    else:
        ids: set[str] = set()
        for item in artifacts:
            if not isinstance(item, dict):
                errors.append("artifact entries must be objects")
                continue
            ident = item.get("id")
            if not isinstance(ident, str) or not ident:
                errors.append("artifact id must be a non-empty string")
            elif ident in ids:
                errors.append(f"duplicate artifact id: {ident}")
            else:
                ids.add(ident)
            filename = item.get("file")
            if not isinstance(filename, str) or not filename or Path(filename).name != filename:
                errors.append(f"{ident}: file must be a basename")
            sha = item.get("sha256")
            if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                errors.append(f"{ident}: sha256 must be 64 lowercase hex characters")
            if item.get("darwin_compatible") is not False:
                errors.append(f"{ident}: darwin_compatible must be false until tested")
    return errors


def build_report(contract: dict[str, Any], firmware_dir: Path | None) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    any_present = False
    all_match = True
    for item in contract.get("artifacts", []):
        filename = item["file"]
        path = firmware_dir / filename if firmware_dir else None
        present = bool(path and path.is_file())
        record: dict[str, Any] = {
            "id": item["id"],
            "file": filename,
            "expected_bytes": item.get("bytes"),
            "expected_sha256": item["sha256"],
            "present": present,
            "match": False,
            "darwin_compatible": False,
        }
        if present and path:
            any_present = True
            actual_bytes = path.stat().st_size
            actual_sha = digest(path)
            record["actual_bytes"] = actual_bytes
            record["actual_sha256"] = actual_sha
            size_ok = item.get("bytes") is None or actual_bytes == item["bytes"]
            record["match"] = size_ok and actual_sha == item["sha256"]
            if not record["match"]:
                all_match = False
        else:
            all_match = False
        artifacts.append(record)
    return {
        "schema": 1,
        "board": contract.get("board"),
        "soc": contract.get("soc"),
        "available": any_present,
        "all_declared_artifacts_match": bool(artifacts) and all_match,
        "darwin_load_allowed": False,
        "hardware_validation_required": True,
        "firmware_dir": str(firmware_dir) if firmware_dir else None,
        "artifacts": artifacts,
        "notes": [
            "Firmware metadata is evidence only; no blob is copied into a kernel, ESP or userdata image.",
            "Android/WOA firmware does not establish a Darwin driver or a working iOS hardware path.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--firmware-dir", type=Path,
                        help="private directory containing exact declared files")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-present", action="store_true",
                        help="fail if every declared artifact is not present and hash-matching")
    args = parser.parse_args()
    contract_path = args.contract.resolve()
    if not contract_path.is_file():
        parser.error(f"contract not found: {contract_path}")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    errors = validate_contract(contract)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    firmware_dir = args.firmware_dir.resolve() if args.firmware_dir else None
    if firmware_dir and not firmware_dir.is_dir():
        parser.error(f"firmware directory not found: {firmware_dir}")
    report = build_report(contract, firmware_dir)
    rendered = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(f"PASS: Polaris firmware contract is valid; available={report['available']}")
    print(f"Declared artifacts: {len(report['artifacts'])}; all_match={report['all_declared_artifacts_match']}")
    print("Darwin firmware loading remains disabled; no device or blob mutation performed")
    if args.require_present and not report["all_declared_artifacts_match"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
