#!/usr/bin/env python3
"""Create a local, provenance-first Polaris driver input bundle.

The bundle is intentionally not a kext/rootfs and is never flashable by
itself.  It records the Darwin source components, protocol tests, WOA/MIUI
evidence and optional local firmware hashes.  Vendor binaries are copied only
when the caller explicitly requests ``--copy-vendor``; the default is a
metadata-only bundle suitable for CI and source review.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

DRIVER_DIRS = (
    "GopFramebuffer",
    "ShengUfs",
    "PolarisA630Probe",
    "PolarisGeniI2c",
    "PolarisPmicInput",
    "PolarisProtocols",
    "PolarisSynapticsTouch",
    "PolarisTouch",
    "PolarisTransportContracts",
    "PolarisPeripheralContracts",
    "PolarisNfcContract",
    "PolarisCameraContract",
    "PolarisDisplayContract",
    "PolarisRuntime",
    "PolarisPmicRuntime",
    "PolarisHidInput",
)

FIRMWARE_NAMES = {
    "a630_gmu.bin",
    "a630_sqe.fw",
    "a630_zap.mdt",
    "a630_zap.b00",
    "a630_zap.b01",
    "a630_zap.b02",
    "a630_zap.elf",
    "bdwlan.bin",
    "wlanmdsp.mbn",
    "crbtfw20.tlv",
    "crnv20.bin",
    "crnv21.bin",
    "libpn553_fw.so",
    "libpn553_rec.so",
    "com.qti.sensormodule.imx363.bin",
    "com.qti.tuned.semco_imx363.bin",
    "camera_icp.elf",
    "camera_icp_aaaaaa.elf",
    "camera_icp.mbn",
}

# Android vendor partitions are commonly unpacked on a case-insensitive file
# system, while the bundle is also generated on Linux CI.  Keep the canonical
# names above for the manifest, but match extracted filenames case-insensitively
# so files such as ``CAMERA_ICP.elf`` are not silently omitted from provenance.
FIRMWARE_NAMES_CASEFOLD = {name.casefold() for name in FIRMWARE_NAMES}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_source_bytes(path: Path) -> bytes:
    """Read a text source using repository-stable LF line endings.

    Windows checkouts can expose CRLF or mixed line endings even when the
    repository stores LF.  Driver provenance must describe the committed
    source, so normalize only line endings before recording byte counts and
    hashes.  The driver directories contain source/metadata text, not binary
    firmware; vendor binaries continue to use the raw ``sha256`` helper.
    """

    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def source_inventory() -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for name in DRIVER_DIRS:
        directory = ROOT / "drivers" / name
        if not directory.is_dir():
            continue
        for path in sorted(
            p for p in directory.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        ):
            # Source text and build metadata are safe to hash into the bundle;
            # no generated objects or proprietary input are pulled in here.
            data = canonical_source_bytes(path)
            files.append({
                "path": relative(path, ROOT),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
    return files


def vendor_inventory(vendor_root: Path | None, out: Path, copy_vendor: bool) -> list[dict[str, Any]]:
    if vendor_root is None or not vendor_root.is_dir():
        return []
    destination = out / "vendor" if copy_vendor else None
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    copied_names: set[str] = set()
    for path in sorted(
        p for p in vendor_root.rglob("*")
        if p.is_file() and p.name.casefold() in FIRMWARE_NAMES_CASEFOLD
    ):
        record: dict[str, Any] = {
            "name": path.name,
            "source": relative(path, vendor_root),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "copied": False,
            "darwin_driver": False,
        }
        if destination is not None:
            target_name = path.name
            # A vendor tree can contain the same basename in multiple
            # partitions/directories (for example crnv20.bin).  Preserve all
            # evidence files instead of silently overwriting an earlier copy.
            if target_name.casefold() in copied_names:
                target_name = f"{sha256(path)[:12]}-{path.name}"
                suffix = 1
                while target_name.casefold() in copied_names:
                    target_name = f"{sha256(path)[:12]}-{suffix}-{path.name}"
                    suffix += 1
            copied_names.add(target_name.casefold())
            target = destination / target_name
            shutil.copy2(path, target)
            record["path"] = target.relative_to(out).as_posix()
            record["copied"] = True
        entries.append(record)
    return entries


def build_bundle(output: Path, vendor_root: Path | None, copy_vendor: bool) -> dict[str, Any]:
    output = output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    hardware_contract = ROOT / "research" / "polaris-hardware-contract.json"
    driver_matrix = ROOT / "research" / "polaris-driver-matrix.json"
    a630_resources = ROOT / "research" / "polaris-a630-resources.json"
    woa_evidence = ROOT / "research" / "polaris-woa-evidence.json"
    manifest: dict[str, Any] = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "board": "xiaomi,polaris",
        "variant": {"ram_gib": 6, "storage_gib": 128},
        "darwin": {"kernel_family": "UniXNU Darwin 23", "source_components": source_inventory()},
        "inputs": {
            "hardware_contract": hardware_contract.is_file(),
            "driver_matrix": driver_matrix.is_file(),
            "a630_resources": a630_resources.is_file(),
            "woa_evidence": woa_evidence.is_file(),
            "vendor_root_supplied": vendor_root is not None and vendor_root.is_dir(),
            "vendor_binaries_copied": bool(copy_vendor),
        },
        "vendor_firmware": vendor_inventory(vendor_root, output, copy_vendor),
        "policy": {
            "metadata_only": not copy_vendor,
            "android_or_windows_binaries_are_darwin_drivers": False,
            "flashable": False,
            "hardware_tested": False,
            "fingerprint": "deferred",
        },
        "open_gates": [
            "Darwin transport and userland service for each required subsystem",
            "Apple/iPadOS rootfs, prelink and trust-chain qualification",
            "temporary Polaris boot validation with per-device logs",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if hardware_contract.is_file():
        shutil.copy2(hardware_contract, output / hardware_contract.name)
    if driver_matrix.is_file():
        shutil.copy2(driver_matrix, output / driver_matrix.name)
    if a630_resources.is_file():
        shutil.copy2(a630_resources, output / a630_resources.name)
    if woa_evidence.is_file():
        shutil.copy2(woa_evidence, output / woa_evidence.name)
    (output / "README.txt").write_text(
        "Polaris UniXNU local driver input bundle\n"
        "flashable=false\n"
        "This bundle contains source provenance and optional user-supplied firmware inputs.\n"
        "It does not claim that any subsystem is a working iOS/Darwin driver.\n",
        encoding="utf-8",
    )
    entries: list[str] = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            entries.append(f"{sha256(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS").write_text("\n".join(entries) + "\n", encoding="ascii")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--vendor-root", type=Path)
    parser.add_argument("--copy-vendor", action="store_true",
                        help="copy explicitly supplied local firmware into the bundle")
    args = parser.parse_args()
    manifest = build_bundle(args.out, args.vendor_root, args.copy_vendor)
    print(f"wrote local Polaris driver bundle: {args.out.resolve()}")
    print(f"source_files={len(manifest['darwin']['source_components'])}")
    print(f"vendor_files={len(manifest['vendor_firmware'])} copied={args.copy_vendor}")
    print("flashable=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
