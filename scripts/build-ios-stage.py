#!/usr/bin/env python3
"""Assemble the experimental Polaris iPadOS 17 stage without touching a phone.

This is the host-side join point for the prelinked Darwin 23 kernel, iPadOS
trust caches, the FAT ESP and the SHNGROOT root image.  It deliberately emits
an evidence package with ``flashable=false``: a successful assembly does not
prove that NativeUfs can mount the root on a real SDM845 device, nor that the
Apple userland accepts the retargeted ADT.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(script: str, args: list[str]) -> None:
    command = [sys.executable, str(ROOT / "scripts" / script), *args]
    subprocess.run(command, cwd=ROOT, check=True)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require_raw_apfs(path: Path) -> dict[str, int]:
    with path.open("rb") as stream:
        header = stream.read(48)
    # nx_superblock_t starts with the 32-byte obj_phys_t, including its
    # checksum. NXSB is at byte 32, not at the beginning of the disk image.
    if len(header) != 48 or header[32:36] != b"NXSB":
        raise SystemExit(
            f"{path}: expected a raw APFS container with NXSB at byte 32; "
            "decode a UDIF/LZFSE wrapper before assembling SHNGROOT"
        )
    block_size, block_count = struct.unpack_from("<IQ", header, 36)
    if (block_size < 4096 or block_size > 65536 or
            block_size & (block_size - 1) or block_count == 0):
        raise SystemExit(f"{path}: invalid APFS container geometry")
    container_bytes = block_size * block_count
    if container_bytes > path.stat().st_size:
        raise SystemExit(f"{path}: APFS container is truncated")
    return {"block_size": block_size, "block_count": block_count,
            "container_bytes": container_bytes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", type=Path, required=True,
                        help="prelinked kernel.macho with its kernel.json report")
    parser.add_argument("--adt", type=Path, required=True,
                        help="Polaris/iPad identity ADT candidate")
    parser.add_argument("--efi", type=Path, required=True,
                        help="EFI output containing UniXNU.efi and DarwinBoot.efi")
    parser.add_argument("--static-trust", type=Path, required=True,
                        help="OS-volume trust cache from the IPSW")
    parser.add_argument("--system-trust", type=Path, required=True,
                        help="SystemOS trust cache from the IPSW")
    parser.add_argument("--os", type=Path, required=True,
                        help="raw OS APFS image")
    parser.add_argument("--system-os", type=Path, required=True,
                        help="raw SystemOS APFS image")
    parser.add_argument("--out", type=Path, required=True,
                        help="output directory for the stage")
    parser.add_argument("--package", type=Path,
                        help="optional guarded package directory")
    args = parser.parse_args()

    paths = [args.kernel, args.adt, args.efi, args.static_trust, args.system_trust,
             args.os, args.system_os]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        parser.error("missing input(s): " + ", ".join(missing))
    require_raw_apfs(args.os)
    require_raw_apfs(args.system_os)

    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    trust = out / "trust.bundle"
    run("make-trust-bundle.py", ["--static", str(args.static_trust),
                                  "--system", str(args.system_trust), "--out", str(trust)])

    esp_tree = out / "esp"
    esp_image = out / "esp.img"
    run("make-ios-esp.py", ["--kernel", str(args.kernel), "--adt", str(args.adt),
                             "--trust", str(trust), "--efi", str(args.efi),
                             "--out", str(esp_image), "--tree", str(esp_tree)])

    darwin_root = out / "darwin-root.img"
    run("make-userdata-linux.py", ["--os", str(args.os), "--system-os", str(args.system_os),
                                    "--partition", "darwin", "--out", str(darwin_root)])

    manifest = {
        "schema": 1,
        "board": "xiaomi,polaris",
        "variant": {"ram_gib": 6, "storage_gib": 128},
        "target": "UniXNU Darwin 23 / iPadOS 17 experimental stage",
        "flashable": False,
        "safe_to_flash": False,
        "hardware_tested": False,
        "temporary_boot_tested": False,
        "inputs": {
            "kernel": {"path": args.kernel.name, "bytes": args.kernel.stat().st_size,
                       "sha256": digest(args.kernel)},
            "adt": {"path": args.adt.name, "bytes": args.adt.stat().st_size,
                    "sha256": digest(args.adt)},
            "esp_image": {"path": esp_image.name, "bytes": esp_image.stat().st_size,
                          "sha256": digest(esp_image)},
            "trust_bundle": {"path": trust.name, "bytes": trust.stat().st_size,
                             "sha256": digest(trust)},
            "darwin_root": {"path": darwin_root.name, "bytes": darwin_root.stat().st_size,
                            "sha256": digest(darwin_root)},
        },
        "blockers": [
            "prelinked kernel has not been temporarily booted on this Polaris",
            "NativeUfs root mount and APFS handoff are unverified",
            "Apple userland, trust chain and retargeted ADT are unverified on hardware",
            "GPU, Wi-Fi, Bluetooth, NFC and camera Darwin backends are not hardware-tested",
        ],
        "notes": [
            "This directory is assembled without adb, fastboot or device access.",
            "darwin-root.img targets the separate darwin partition; userdata retains the ESP.",
            "Do not change flashable to true without an independent temporary-boot report.",
        ],
    }
    (out / "ios-stage-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.package:
        package = args.package.resolve()
        if package.exists():
            shutil.rmtree(package)
        run("make-polaris-package.py", ["--esp", str(esp_tree), "--esp-image", str(esp_image),
                                         "--kernel", str(args.kernel), "--darwin-root",
                                         str(darwin_root), "--out", str(package)])
        (package / "ios-stage-manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"assembled experimental Polaris iOS stage: {out}")
    print("flashable=false; no phone access performed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
