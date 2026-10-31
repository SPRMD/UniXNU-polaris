#!/usr/bin/env python3
"""Verify a guarded Polaris package without accessing a device.

The package builder writes both a manifest and a SHA256SUMS file.  This
checker validates the complete file set, then cross-checks manifest input
paths and hashes.  It never invokes adb or fastboot and does not change the
package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


SUM_RE = re.compile(r"^(?P<digest>[0-9a-fA-F]{64})  (?P<path>.+)$")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_member(root: Path, relative: str) -> Path:
    # The checker runs on Linux in CI, but packages are consumed on Windows
    # too.  Reject Windows drive/UNC paths and backslash traversal explicitly
    # instead of relying on the host platform's Path separator rules.
    if re.match(r"^[A-Za-z]:", relative) or relative.startswith(("\\\\", "//", "/\\")):
        raise ValueError(f"unsafe package path: {relative}")
    if "\\" in relative:
        raise ValueError(f"unsafe package path: {relative}")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe package path: {relative}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"package path escapes root: {relative}") from error
    return resolved


def verify_sums(root: Path) -> int:
    sums_path = root / "SHA256SUMS"
    if not sums_path.is_file():
        raise ValueError("missing SHA256SUMS")
    seen: set[str] = set()
    for number, line in enumerate(sums_path.read_text(encoding="ascii").splitlines(), 1):
        if not line.strip():
            continue
        match = SUM_RE.fullmatch(line)
        if match is None:
            raise ValueError(f"invalid SHA256SUMS line {number}")
        relative = match.group("path")
        if relative in seen:
            raise ValueError(f"duplicate checksum entry: {relative}")
        seen.add(relative)
        path = safe_member(root, relative)
        if not path.is_file():
            raise ValueError(f"checksum target is missing: {relative}")
        actual = digest(path)
        if actual.lower() != match.group("digest").lower():
            raise ValueError(f"SHA-256 mismatch: {relative}")
    if not seen:
        raise ValueError("SHA256SUMS is empty")
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    omitted = sorted(actual_files - seen)
    if omitted:
        raise ValueError("unlisted package files: " + ", ".join(omitted))
    unexpected = sorted(seen - actual_files)
    if unexpected:
        raise ValueError("checksum entries without files: " + ", ".join(unexpected))
    return len(seen)


def verify_manifest(root: Path) -> dict:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("missing manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid manifest.json: {error}") from error
    if manifest.get("board") != "xiaomi,polaris":
        raise ValueError("manifest board is not xiaomi,polaris")
    if not isinstance(manifest.get("flashable"), bool):
        raise ValueError("manifest flashable must be boolean")
    if not isinstance(manifest.get("safe_to_flash"), bool):
        raise ValueError("manifest safe_to_flash must be boolean")
    if manifest["safe_to_flash"] != manifest["flashable"]:
        raise ValueError("manifest safe_to_flash must match flashable")
    if not isinstance(manifest.get("blockers"), list):
        raise ValueError("manifest blockers must be a list")
    if manifest["flashable"] and manifest["blockers"]:
        raise ValueError("flashable package still has blockers")
    for key in ("hardware_tested", "temporary_boot_tested", "userland_tested"):
        if not isinstance(manifest.get(key), bool):
            raise ValueError(f"manifest {key} must be boolean")
    if manifest["flashable"] and not all(
            manifest[key] for key in ("hardware_tested", "temporary_boot_tested", "userland_tested")):
        raise ValueError("flashable package lacks hardware, temporary-boot, or userland validation")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("manifest inputs must be an object")
    for name, fact in inputs.items():
        if not isinstance(fact, dict) or not fact.get("present"):
            continue
        relative = fact.get("path")
        if not isinstance(relative, str):
            raise ValueError(f"manifest input {name} has no relative path")
        path = safe_member(root, relative)
        if not path.exists():
            raise ValueError(f"manifest input {name} is missing: {relative}")
        expected = fact.get("sha256")
        if expected and path.is_file() and digest(path).lower() != str(expected).lower():
            raise ValueError(f"manifest input hash mismatch: {name}")
    # An evidence-only package must never describe device access or a true
    # installer command set.  A future qualified package can satisfy these
    # checks with the independent validation report required by the builder.
    if not manifest["flashable"]:
        access = manifest.get("device_access", {})
        if any(bool(access.get(key)) for key in ("adb", "fastboot", "partition_writes")):
            raise ValueError("non-flashable package claims device access")
        installer = manifest.get("installer", {})
        if installer.get("commands"):
            raise ValueError("non-flashable package contains installer commands")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    root = args.package.resolve()
    if not root.is_dir():
        parser.error(f"package directory not found: {root}")
    try:
        manifest = verify_manifest(root)
        count = verify_sums(root)
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: verified {count} package files")
    print(f"board={manifest['board']} flashable={str(manifest['flashable']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
