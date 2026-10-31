#!/usr/bin/env python3
"""Build a local UniXNU SHNGROOT userdata image from extracted IPSW DMGs.

The two source files must already be downloaded and verified against the
board's IPSW pins.  This script uses the bundled Python LZFSE extension on
Windows and never opens a device or invokes fastboot.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT
SECTOR = 512
MIB = 1 << 20
CHUNK = 8 << 20
ZERO_FILL, RAW, IGNORE = 0x00000000, 0x00000001, 0x00000002
ZLIB, BZIP2, LZFSE = 0x80000005, 0x80000006, 0x80000007


def load_lzfse():
    try:
        import lzfse  # type: ignore
        return lzfse
    except ImportError:
        deps = ROOT / "tools" / "pydeps"
        if deps.is_dir():
            sys.path.insert(0, str(deps))
            import lzfse  # type: ignore
            return lzfse
        raise


def udif_chunks(path: Path):
    """Return (raw_size, chunks) using the upstream UDIF parser."""
    scripts = PROJECT / "upstream" / "UniXNU" / "scripts"
    if scripts.is_dir():
        sys.path.insert(0, str(scripts))
        try:
            from unixnu.udif import Image  # type: ignore
        except ImportError:
            pass
        else:
            image = Image(path)
            return image.size, image.chunks

    # Host tests use small raw fixtures and a repository checkout does not
    # carry the optional UniXNU UDIF parser.  Treat an input without that
    # parser as an already-decoded raw image, but reject a recognizable UDIF
    # container instead of silently copying compressed bytes into userdata.
    trailer = b""
    if path.stat().st_size >= 512:
        with path.open("rb") as stream:
            stream.seek(-512, 2)
            trailer = stream.read(512)
    if b"koly" in trailer:
        raise RuntimeError(
            f"{path}: upstream UniXNU UDIF parser is required for a DMG input"
        )
    return path.stat().st_size, None


def raw_blocks(path: Path):
    size, chunks = udif_chunks(path)
    if chunks is None:
        with path.open("rb") as stream:
            while block := stream.read(CHUNK):
                yield block
        return
    lzfse = load_lzfse()
    import bz2
    import zlib
    with path.open("rb") as stream:
        for start, length, kind, offset, stored in chunks:
            if kind in (ZERO_FILL, IGNORE):
                data = bytes(length)
            else:
                stream.seek(offset)
                data = stream.read(stored)
                if kind == ZLIB:
                    data = zlib.decompress(data)
                elif kind == BZIP2:
                    data = bz2.decompress(data)
                elif kind == LZFSE:
                    data = lzfse.decompress(data)
                elif kind != RAW:
                    raise ValueError(f"unsupported UDIF chunk type {kind:#x}")
            if len(data) != length:
                raise ValueError(f"{path}: chunk at {start:#x} produced {len(data)} bytes, expected {length}")
            for position in range(0, len(data), CHUNK):
                yield data[position:position + CHUNK]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def shngroot_facts(path: Path) -> dict[str, object]:
    """Return the host-side facts needed to validate a SHNGROOT image.

    Keep this parser next to the image builder so callers can validate the
    exact artifact they just produced without importing the root-stage report
    script.  It only reads the 4 KiB manifest and hashes the file; it never
    opens a device or invokes fastboot.
    """
    if not path.is_file() or path.stat().st_size < 4096:
        return {"valid": False, "reason": "missing or shorter than manifest block"}
    with path.open("rb") as stream:
        header = stream.read(4096)
    if header[:8] != b"SHNGROOT":
        return {"valid": False, "reason": "bad magic"}
    version, count, image_bytes = struct.unpack_from("<IIQ", header, 8)
    checksum_ok = hashlib.sha256(header[:4064]).digest() == header[4064:4096]
    return {
        "valid": version == 1 and count == 2 and checksum_ok and image_bytes == path.stat().st_size,
        "version": version,
        "windows": count,
        "image_bytes": image_bytes,
        "manifest_checksum_ok": checksum_ok,
        "sha256": sha256(path),
    }


def build(os_dmg: Path, system_dmg: Path, output: Path, report_path: Path, board: Path):
    os_size, _ = udif_chunks(os_dmg)
    system_size, _ = udif_chunks(system_dmg)
    board_data = tomllib.loads(board.read_text(encoding="utf-8"))
    geometry = board_data["userdata"]
    capacity = (geometry["last_lba"] - geometry["first_lba"] + 1) * geometry.get("lba_bytes", SECTOR)
    cursor = MIB
    windows = []
    for name, size, source in (("OS", os_size, os_dmg), ("SystemOS", system_size, system_dmg)):
        windows.append((name, cursor, size, source))
        cursor += (size + MIB - 1) // MIB * MIB
    if cursor > capacity:
        raise ValueError(f"SHNGROOT image needs {cursor} bytes, userdata capacity is {capacity}")

    output.parent.mkdir(parents=True, exist_ok=True)
    digest_windows = []
    with output.open("wb") as target:
        target.truncate(cursor)
        for name, offset, size, source in windows:
            target.seek(offset)
            digest = hashlib.sha256()
            written = 0
            for block in raw_blocks(source):
                digest.update(block)
                target.write(block)
                written += len(block)
            if written != size:
                raise ValueError(f"{source}: decoded {written} bytes, expected {size}")
            digest_windows.append((name, offset, size, digest.digest()))

        header = bytearray(4096)
        header[0:8] = b"SHNGROOT"
        struct.pack_into("<IIQ", header, 8, 1, len(digest_windows), cursor)
        for index, (name, offset, size, digest) in enumerate(digest_windows):
            struct.pack_into(
                "<32sQQII32s40s", header, 24 + 128 * index,
                name.encode("ascii"), offset, size, SECTOR, 1, digest, bytes(40)
            )
        header[4064:4096] = hashlib.sha256(bytes(header[:4064])).digest()
        target.seek(0)
        target.write(header)

    report = {
        "image_bytes": cursor,
        "image_sha256": sha256(output),
        "manifest_sha256": hashlib.sha256(bytes(header)).hexdigest(),
        "userdata_capacity_bytes": capacity,
        "userdata_geometry": {
            "first_lba": geometry["first_lba"],
            "last_lba": geometry["last_lba"],
            "lba_bytes": geometry.get("lba_bytes", SECTOR),
            "provisional": True,
        },
        "windows": [
            {"name": name, "offset": offset, "size": size, "sha256": digest.hex()}
            for name, offset, size, digest in digest_windows
        ],
        "sources": {
            "OS": {"path": str(os_dmg), "dmg_sha256": sha256(os_dmg)},
            "SystemOS": {"path": str(system_dmg), "dmg_sha256": sha256(system_dmg)},
        },
        "hardware_tested": False,
        "flash_command": f"fastboot flash userdata {output}",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--os", type=Path, default=PROJECT / "inputs/ipsw/044-76040-038.dmg")
    parser.add_argument("--system-os", type=Path, default=PROJECT / "inputs/ipsw/044-76034-038.dmg")
    parser.add_argument("--board", type=Path, default=PROJECT / "device-repo/UniXNU-polaris/board.toml")
    parser.add_argument("--output", type=Path, default=PROJECT / "out/polaris/userdata/userdata-root.img")
    parser.add_argument("--report", type=Path, default=PROJECT / "out/polaris/userdata/userdata-root.json")
    args = parser.parse_args()
    for path in (args.os, args.system_os, args.board):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    build(args.os.resolve(), args.system_os.resolve(), args.output.resolve(), args.report.resolve(), args.board.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
