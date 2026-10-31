#!/usr/bin/env python3
"""Verify a Polaris driver provenance bundle without accessing a device.

The driver bundle has a different manifest schema from the guarded installer
package.  This checker validates its complete checksum list, the fail-closed
policy, copied vendor firmware records, and (when supplied) the source
inventory against a local repository checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


SUM_RE = re.compile(r"^(?P<digest>[0-9a-fA-F]{64})  (?P<path>.+)$")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def safe_member(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("bundle path is empty")
    if re.match(r"^[A-Za-z]:", relative) or relative.startswith(("/", "\\\\")):
        raise ValueError(f"unsafe bundle path: {relative}")
    if "\\" in relative:
        raise ValueError(f"unsafe bundle path: {relative}")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe bundle path: {relative}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"bundle path escapes root: {relative}") from error
    return resolved


def verify_sums(root: Path) -> int:
    sums_path = root / "SHA256SUMS"
    if not sums_path.is_file():
        raise ValueError("missing SHA256SUMS")
    listed: set[str] = set()
    for number, line in enumerate(sums_path.read_text(encoding="ascii").splitlines(), 1):
        if not line.strip():
            continue
        match = SUM_RE.fullmatch(line)
        if match is None:
            raise ValueError(f"invalid SHA256SUMS line {number}")
        relative = match.group("path")
        if relative in listed:
            raise ValueError(f"duplicate checksum entry: {relative}")
        listed.add(relative)
        target = safe_member(root, relative)
        if not target.is_file():
            raise ValueError(f"checksum target is missing: {relative}")
        actual = digest(target)
        if actual.lower() != match.group("digest").lower():
            raise ValueError(f"SHA-256 mismatch: {relative}")
    if not listed:
        raise ValueError("SHA256SUMS is empty")
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if actual_files - listed:
        raise ValueError("unlisted bundle files: " + ", ".join(sorted(actual_files - listed)))
    if listed - actual_files:
        raise ValueError("checksum entries without files: " + ", ".join(sorted(listed - actual_files)))
    return len(listed)


def verify_source_inventory(manifest: dict[str, Any], source_root: Path | None) -> int:
    darwin = manifest.get("darwin")
    if not isinstance(darwin, dict):
        raise ValueError("manifest darwin section is missing")
    components = darwin.get("source_components")
    if not isinstance(components, list) or not components:
        raise ValueError("manifest source_components is empty")
    for item in components:
        if not isinstance(item, dict):
            raise ValueError("invalid source component record")
        relative = item.get("path")
        if (not isinstance(relative, str) or not relative or "\\" in relative or
                re.match(r"^[A-Za-z]:", relative) or
                relative.startswith(("/", "\\\\")) or
                Path(relative).is_absolute() or ".." in Path(relative).parts):
            raise ValueError(f"unsafe source component path: {relative}")
        expected_bytes = item.get("bytes")
        expected_hash = item.get("sha256")
        if not isinstance(expected_bytes, int) or not isinstance(expected_hash, str):
            raise ValueError(f"incomplete source component record: {relative}")
        if source_root is not None:
            source = safe_member(source_root, relative)
            if not source.is_file():
                raise ValueError(f"source component is missing: {relative}")
            if source.stat().st_size != expected_bytes:
                raise ValueError(f"source byte count mismatch: {relative}")
            if digest(source).lower() != expected_hash.lower():
                raise ValueError(f"source SHA-256 mismatch: {relative}")
    return len(components)


def verify_manifest(root: Path, source_root: Path | None) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("missing manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid manifest.json: {error}") from error
    if manifest.get("schema") != 1 or manifest.get("board") != "xiaomi,polaris":
        raise ValueError("unsupported bundle schema or board")
    variant = manifest.get("variant")
    if variant != {"ram_gib": 6, "storage_gib": 128}:
        raise ValueError("bundle variant is not the Polaris 6 GiB/128 GiB target")
    policy = manifest.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("manifest policy is missing")
    if policy.get("flashable") is not False or policy.get("hardware_tested") is not False:
        raise ValueError("driver bundle must remain non-flashable and untested")
    if policy.get("fingerprint") != "deferred":
        raise ValueError("fingerprint gate must remain deferred")
    if policy.get("android_or_windows_binaries_are_darwin_drivers") is not False:
        raise ValueError("vendor evidence must not be labelled as Darwin drivers")
    if not isinstance(manifest.get("open_gates"), list) or not manifest["open_gates"]:
        raise ValueError("manifest open_gates is missing")
    verify_source_inventory(manifest, source_root)
    vendor = manifest.get("vendor_firmware")
    if not isinstance(vendor, list):
        raise ValueError("vendor_firmware is missing")
    for record in vendor:
        if not isinstance(record, dict) or record.get("darwin_driver") is not False:
            raise ValueError("vendor record is incorrectly labelled")
        if record.get("copied"):
            relative = record.get("path")
            target = safe_member(root, relative)
            if not target.is_file():
                raise ValueError(f"copied vendor file is missing: {relative}")
            if target.stat().st_size != record.get("bytes"):
                raise ValueError(f"copied vendor byte count mismatch: {relative}")
            if digest(target).lower() != str(record.get("sha256", "")).lower():
                raise ValueError(f"copied vendor SHA-256 mismatch: {relative}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument(
        "--source-root",
        type=Path,
        help="optional repository root used to re-hash manifest source_components",
    )
    args = parser.parse_args()
    root = args.bundle.resolve()
    source_root = args.source_root.resolve() if args.source_root else None
    if not root.is_dir():
        parser.error(f"bundle directory not found: {root}")
    if source_root is not None and not source_root.is_dir():
        parser.error(f"source root not found: {source_root}")
    try:
        manifest = verify_manifest(root, source_root)
        count = verify_sums(root)
        source_count = len(manifest["darwin"]["source_components"])
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: verified {count} bundle files")
    print(f"source_components={source_count} vendor_files={len(manifest['vendor_firmware'])}")
    print("flashable=false hardware_tested=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
