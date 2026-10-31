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
import uuid
import zlib

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


def rewrite_package_sums(package: Path) -> None:
    """Refresh the package checksum list after adding stage evidence files."""
    entries: list[str] = []
    for path in sorted(package.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            entries.append(f"{digest(path)}  {path.relative_to(package).as_posix()}")
    (package / "SHA256SUMS").write_text("\n".join(entries) + "\n", encoding="ascii")


def require_distinct_images(os_path: Path, system_os_path: Path) -> None:
    """Reject accidentally reusing the OS image as SystemOS.

    The iPadOS restore manifest names these as separate APFS volumes.  Keeping
    this check here makes a workflow typo fail before any extraction or
    userdata assembly, even when both paths happen to exist.
    """
    if os_path.resolve() == system_os_path.resolve():
        raise SystemExit("OS and SystemOS inputs must be different files")
    if digest(os_path) == digest(system_os_path):
        raise SystemExit("OS and SystemOS inputs must have different content")


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


def apfs_partition(stream, image_bytes: int, base: int = 0) -> tuple[int, int]:
    """Locate one APFS partition in a 512-byte-sector Apple disk image.

    The phone GPT uses different geometry; this only parses decoded IPSW disks.
    Validate header/table CRCs and every occupied extent before copying bytes.
    """
    stream.seek(base + 512)
    header = bytearray(stream.read(512))
    if len(header) != 512 or header[:8] != b'EFI PART':
        raise SystemExit('expected raw APFS or a GPT-wrapped IPSW disk')
    revision, length, checksum, reserved = struct.unpack_from('<4I', header, 8)
    if revision != 0x10000 or not 92 <= length <= 512 or reserved:
        raise SystemExit('invalid GPT header')
    struct.pack_into('<I', header, 16, 0)
    if zlib.crc32(header[:length]) != checksum:
        raise SystemExit('GPT header checksum mismatch')
    current, backup, first, last = struct.unpack_from('<4Q', header, 24)
    table_lba, count, stride, table_crc = struct.unpack_from('<QIII', header, 72)
    sectors = image_bytes // 512
    if (current != 1 or not 2 <= backup < sectors or not 2 <= first <= last < backup or
            not 1 <= count <= 4096 or stride < 128 or stride > 4096 or stride % 128 or
            table_lba < 2 or table_lba * 512 + count * stride > first * 512):
        raise SystemExit('invalid GPT geometry')
    stream.seek(base + table_lba * 512)
    entries = stream.read(count * stride)
    if len(entries) != count * stride or zlib.crc32(entries) != table_crc:
        raise SystemExit('GPT entry checksum mismatch')
    apfs_type = uuid.UUID('7C3457EF-0000-11AA-AA11-00306543ECAC').bytes_le
    extents, matches, identifiers = [], [], set()
    for index in range(count):
        entry = entries[index * stride:(index + 1) * stride]
        if entry[:16] == bytes(16):
            continue
        start, end = struct.unpack_from('<QQ', entry, 32)
        identifier = entry[16:32]
        if (not first <= start <= end <= last or identifier == bytes(16) or
                identifier in identifiers or any(start <= b and a <= end for a, b in extents)):
            raise SystemExit('invalid or overlapping GPT partitions')
        identifiers.add(identifier)
        extents.append((start, end))
        if entry[:16] == apfs_type:
            matches.append((start * 512, (end - start + 1) * 512))
    if len(matches) != 1:
        raise SystemExit('expected exactly one APFS partition')
    return matches[0]


def unwrap_apfs_partition(path: Path, workdir: Path) -> tuple[Path, dict[str, int]]:
    with path.open('rb') as source:
        offset, length = apfs_partition(source, path.stat().st_size)
        source.seek(offset)
        header = source.read(48)
        if len(header) != 48 or header[32:36] != b'NXSB':
            raise SystemExit('GPT APFS partition does not contain NXSB')
        block_size, blocks = struct.unpack_from('<IQ', header, 36)
        if (block_size < 4096 or block_size > 65536 or block_size & (block_size - 1)
                or not blocks or block_size * blocks > length):
            raise SystemExit('APFS container exceeds its GPT partition')
        workdir.mkdir(parents=True, exist_ok=True)
        output = workdir / (path.name + '.apfs.img')
        if output.resolve() == path.resolve():
            raise SystemExit('APFS output aliases input')
        source.seek(offset)
        remaining = block_size * blocks
        with output.open('wb') as target:
            while remaining:
                data = source.read(min(8 * 1024 * 1024, remaining))
                if not data:
                    raise SystemExit('truncated APFS partition')
                target.write(data)
                remaining -= len(data)
    geometry = require_raw_apfs(output)
    geometry['source_partition_offset'] = offset
    geometry['source_partition_bytes'] = length
    return output, geometry


def normalize_apfs_input(path: Path, workdir: Path) -> tuple[Path, dict[str, int]]:
    """Return a raw APFS image, extracting a UDIF wrapper when necessary.

    Apple IPSW OS/SystemOS members are commonly UDIF/LZFSE containers.  The
    userdata assembler needs the APFS container itself, so keep the original
    input immutable and place the decoded image under the stage work tree.
    """
    try:
        return path, require_raw_apfs(path)
    except SystemExit:
        try:
            with path.open("rb") as stream:
                stream.seek(-512, 2)
                is_udif = stream.read(4) == b"koly"
        except (OSError, ValueError):
            is_udif = False
        if not is_udif:
            return unwrap_apfs_partition(path, workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        raw = workdir / (path.name + ".raw.img")
        run("udif-extract.py", [str(path), str(raw)])
        try:
            return raw, require_raw_apfs(raw)
        except SystemExit:
            return unwrap_apfs_partition(raw, workdir)


def require_distinct_apfs_images(os_image: Path, system_os_image: Path) -> None:
    """Reject an accidental OS/SystemOS alias or duplicate image.

    iPadOS keeps the platform OS volume and the SystemOS cryptex in separate
    APFS containers.  Passing the same member for both inputs can still make
    an apparently well-formed SHNGROOT image, so fail before any userdata
    assembly when the normalized files alias or have identical contents.
    """
    if os_image.resolve() == system_os_image.resolve():
        raise SystemExit("OS and SystemOS inputs must be different APFS images")
    if (os_image.stat().st_size == system_os_image.stat().st_size and
            digest(os_image) == digest(system_os_image)):
        raise SystemExit("OS and SystemOS inputs have identical contents")


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
    parser.add_argument("--firmware", type=Path,
                        help="Polaris boot firmware image or directory to include in the package")
    parser.add_argument("--driver-bundle", type=Path,
                        help="optional local source/firmware provenance bundle")
    parser.add_argument("--input-hash-report", type=Path,
                        help="optional SHA-256 report from check-ios-stage-inputs.py")
    args = parser.parse_args()
    # Subcommands run from ROOT, not from the caller's current directory.
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())

    if args.driver_bundle and not args.driver_bundle.exists():
        parser.error(f"driver bundle not found: {args.driver_bundle}")
    if args.input_hash_report and not args.input_hash_report.is_file():
        parser.error(f"input hash report not found: {args.input_hash_report}")
    paths = [args.kernel, args.adt, args.efi, args.static_trust, args.system_trust,
             args.os, args.system_os]
    if args.driver_bundle:
        paths.append(args.driver_bundle)
    if args.input_hash_report:
        paths.append(args.input_hash_report)
    if args.firmware:
        paths.append(args.firmware)
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        parser.error("missing input(s): " + ", ".join(missing))
    require_distinct_images(args.os, args.system_os)
    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    os_image, os_geometry = normalize_apfs_input(args.os, out / "raw-inputs" / "os")
    system_os_image, system_os_geometry = normalize_apfs_input(
        args.system_os, out / "raw-inputs" / "system-os")
    require_distinct_apfs_images(os_image, system_os_image)

    trust = out / "trust.bundle"
    run("make-trust-bundle.py", ["--static", str(args.static_trust),
                                  "--system", str(args.system_trust), "--out", str(trust)])

    esp_tree = out / "esp"
    esp_image = out / "esp.img"
    run("make-ios-esp.py", ["--kernel", str(args.kernel), "--adt", str(args.adt),
                             "--trust", str(trust), "--efi", str(args.efi),
                             "--out", str(esp_image), "--tree", str(esp_tree),
                             "--ipados-stage"])

    darwin_root = out / "darwin-root.img"
    run("make-userdata-linux.py", ["--os", str(os_image), "--system-os", str(system_os_image),
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
            "kernel": {"path": "esp/EFI/UniXNU/Payloads/kernel.macho", "bytes": args.kernel.stat().st_size,
                       "sha256": digest(args.kernel)},
            "adt": {"path": "esp/EFI/UniXNU/Payloads/kernel.macho.adt", "bytes": args.adt.stat().st_size,
                    "sha256": digest(args.adt)},
            "esp_image": {"path": esp_image.name, "bytes": esp_image.stat().st_size,
                          "sha256": digest(esp_image)},
            "trust_bundle": {"path": trust.name, "bytes": trust.stat().st_size,
                             "sha256": digest(trust)},
            "os": {"source": str(args.os), "raw_path": str(os_image),
                   "sha256": digest(os_image), "geometry": os_geometry},
            "system_os": {"source": str(args.system_os), "raw_path": str(system_os_image),
                          "sha256": digest(system_os_image),
                          "geometry": system_os_geometry},
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
    if args.input_hash_report:
        try:
            hash_report = json.loads(args.input_hash_report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            parser.error(f"invalid input hash report: {error}")
        if hash_report.get("verified") is not True:
            parser.error("input hash report is not marked verified")
        shutil.copy2(args.input_hash_report, out / "ios-input-hashes.json")
        manifest["inputs"]["ios_hash_report"] = {
            "path": "ios-input-hashes.json",
            "bytes": (out / "ios-input-hashes.json").stat().st_size,
            "sha256": digest(out / "ios-input-hashes.json"),
        }
    (out / "ios-stage-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.package:
        package = args.package.resolve()
        if package.exists():
            shutil.rmtree(package)
        package_args = ["--esp", str(esp_tree), "--esp-image", str(esp_image),
                        "--kernel", str(args.kernel), "--darwin-root",
                        str(darwin_root), "--userdata", str(esp_image), "--out", str(package)]
        if args.firmware:
            package_args.extend(["--firmware", str(args.firmware.resolve())])
        if args.driver_bundle:
            package_args.extend(["--driver-bundle", str(args.driver_bundle)])
        run("make-polaris-package.py", package_args)
        if args.input_hash_report:
            shutil.copy2(out / "ios-input-hashes.json", package / "ios-input-hashes.json")
        # The bundle is installed under the loader's sidecar name in a package.
        package_manifest = json.loads(json.dumps(manifest))
        package_manifest["inputs"]["trust_bundle"]["path"] = (
            "esp/EFI/UniXNU/Payloads/kernel.macho.trustcache")
        (package / "ios-stage-manifest.json").write_text(
            json.dumps(package_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        rewrite_package_sums(package)
    print(f"assembled experimental Polaris iOS stage: {out}")
    print("flashable=false; no phone access performed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
