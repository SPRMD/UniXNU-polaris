#!/usr/bin/env python3
"""Create and validate the Android-sparse transport wrapper for Polaris userdata.

The UniXNU userdata builder produces a raw SHNGROOT image.  Fastboot can carry
that image in Android sparse format, which is only a transport encoding: the
expanded bytes must remain identical to the raw image.  This tool uses the
repository's canonical ``make-android-sparse.py`` implementation, verifies the
header and every chunk, compares the expanded SHA-256 with the raw SHA-256, and
writes a small sidecar report.  It never calls adb or fastboot.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
from types import SimpleNamespace
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
UPSTREAM = PROJECT / "upstream" / "UniXNU" / "scripts" / "make-android-sparse.py"
DEFAULT_RAW = PROJECT / "out" / "polaris" / "userdata" / "userdata-root.img"
DEFAULT_SPARSE = PROJECT / "out" / "polaris" / "userdata" / "userdata-root.simg"
DEFAULT_REPORT = PROJECT / "out" / "polaris" / "userdata" / "userdata-root.sparse.json"

MAGIC = 0xED26FF3A
RAW = 0xCAC1
FILL = 0xCAC2
DONT_CARE = 0xCAC3
CRC32 = 0xCAC4
BLOCK = 4096


def load_upstream() -> Any:
    if not UPSTREAM.is_file():
        return SimpleNamespace(
            convert=convert,
            sha256_file=sha256_file,
            expand_hash=expand_hash,
        )
    spec = importlib.util.spec_from_file_location("unixnu_android_sparse", UPSTREAM)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load sparse converter: {UPSTREAM}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def convert(source: Path, target: Path) -> tuple[int, int]:
    """Create the same RAW/FILL-only sparse encoding used by UniXNU."""

    size = source.stat().st_size
    if size % BLOCK:
        raise ValueError("input size must be a multiple of 4096")
    total_blocks = size // BLOCK
    chunks = 0
    with source.open("rb") as src, target.open("wb") as out:
        out.write(b"\0" * 28)
        raw_blocks = bytearray()
        raw_count = 0
        zero_count = 0

        def flush_raw() -> None:
            nonlocal raw_blocks, raw_count, chunks
            if raw_count:
                out.write(struct.pack("<HHII", RAW, 0, raw_count,
                                      12 + len(raw_blocks)))
                out.write(raw_blocks)
                raw_blocks = bytearray()
                raw_count = 0
                chunks += 1

        def flush_zero() -> None:
            nonlocal zero_count, chunks
            if zero_count:
                out.write(struct.pack("<HHII", FILL, 0, zero_count, 16))
                out.write(b"\0\0\0\0")
                zero_count = 0
                chunks += 1

        for _ in range(total_blocks):
            block = src.read(BLOCK)
            if len(block) != BLOCK:
                raise ValueError("short read while creating sparse image")
            if block == bytes(BLOCK):
                flush_raw()
                zero_count += 1
            else:
                flush_zero()
                raw_blocks.extend(block)
                raw_count += 1
                if raw_count == 4096:
                    flush_raw()
        flush_raw()
        flush_zero()
        out.seek(0)
        out.write(struct.pack(
            "<IHHHHIIII", MAGIC, 1, 0, 28, 12, BLOCK,
            total_blocks, chunks, 0,
        ))
    return total_blocks, chunks


def expand_hash(path: Path, expect_blocks: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        header = stream.read(28)
        if len(header) != 28:
            raise ValueError("sparse image header is truncated")
        magic, major, minor, file_header, chunk_header, block_size, total, chunks, _ = struct.unpack(
            "<IHHHHIIII", header
        )
        if (magic, major, file_header, chunk_header, block_size, total) != (
            MAGIC, 1, 28, 12, BLOCK, expect_blocks
        ):
            raise ValueError("bad sparse image header")
        seen = 0
        for _ in range(chunks):
            kind, _reserved, count, total_size = struct.unpack(
                "<HHII", stream.read(12)
            )
            if kind == RAW:
                expected = 12 + count * BLOCK
                if total_size != expected:
                    raise ValueError("bad RAW sparse chunk")
                remaining = count * BLOCK
                while remaining:
                    data = stream.read(min(remaining, 8 * 1024 * 1024))
                    if not data:
                        raise ValueError("truncated RAW sparse chunk")
                    digest.update(data)
                    remaining -= len(data)
            elif kind == FILL:
                if total_size != 16 or stream.read(4) != b"\0\0\0\0":
                    raise ValueError("bad FILL sparse chunk")
                zeros = bytes(1024 * 1024)
                remaining = count * BLOCK
                while remaining:
                    step = min(remaining, len(zeros))
                    digest.update(zeros[:step])
                    remaining -= step
            else:
                raise ValueError(f"unsupported sparse chunk type 0x{kind:04x}")
            seen += count
        if seen != expect_blocks:
            raise ValueError("sparse chunk blocks do not add up")
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT).as_posix()
    except ValueError:
        return str(path.resolve())


def sparse_facts(path: Path) -> dict[str, Any]:
    """Read and validate all sparse chunks without expanding them to disk."""

    size = path.stat().st_size
    with path.open("rb") as stream:
        header = stream.read(28)
        if len(header) != 28:
            raise ValueError("sparse image is shorter than its header")
        magic, major, minor, file_header, chunk_header, block_size, total_blocks, total_chunks, checksum = struct.unpack(
            "<IHHHHIIII", header
        )
        if magic != MAGIC:
            raise ValueError(f"unexpected sparse magic 0x{magic:08x}")
        if (major, file_header, chunk_header, block_size) != (1, 28, 12, BLOCK):
            raise ValueError("unsupported Android sparse header")
        counts = {"raw": 0, "fill": 0, "dont_care": 0, "crc32": 0}
        blocks = 0
        expanded_bytes = 0
        for index in range(total_chunks):
            chunk = stream.read(12)
            if len(chunk) != 12:
                raise ValueError(f"truncated chunk header at index {index}")
            kind, _reserved, count, total_size = struct.unpack("<HHII", chunk)
            if kind == RAW:
                counts["raw"] += 1
                expected = 12 + count * block_size
                if total_size != expected:
                    raise ValueError(f"bad RAW chunk size at index {index}")
                stream.seek(count * block_size, 1)
            elif kind == FILL:
                counts["fill"] += 1
                if total_size != 16:
                    raise ValueError(f"bad FILL chunk size at index {index}")
                fill = stream.read(4)
                if fill != b"\0\0\0\0":
                    raise ValueError("non-zero FILL chunks are not emitted by this tool")
            elif kind == DONT_CARE:
                counts["dont_care"] += 1
                expected = 12
                if total_size != expected:
                    raise ValueError(f"bad DONT_CARE chunk size at index {index}")
            elif kind == CRC32:
                counts["crc32"] += 1
                if total_size != 16 or count != 0:
                    raise ValueError(f"unsupported CRC32 chunk at index {index}")
                stream.seek(4, 1)
            else:
                raise ValueError(f"unknown sparse chunk type 0x{kind:04x}")
            blocks += count
            expanded_bytes += count * block_size
        if blocks != total_blocks:
            raise ValueError(f"sparse chunk blocks {blocks} != header total {total_blocks}")
        end = stream.tell()
        if end != size:
            raise ValueError(f"trailing bytes after sparse chunks: {size - end}")
    return {
        "magic": f"0x{magic:08x}",
        "major_version": major,
        "minor_version": minor,
        "file_header_bytes": file_header,
        "chunk_header_bytes": chunk_header,
        "block_bytes": block_size,
        "total_blocks": total_blocks,
        "total_chunks": total_chunks,
        "checksum": f"0x{checksum:08x}",
        "expanded_bytes": expanded_bytes,
        "chunk_counts": counts,
        "file_bytes": size,
    }


def build_report(raw: Path, sparse: Path, facts: dict[str, Any], raw_sha: str, expanded_sha: str, sparse_sha: str) -> dict[str, Any]:
    source_report = raw.with_suffix(".json")
    capacity: int | None = None
    geometry: dict[str, Any] | None = None
    if source_report.is_file():
        try:
            source_data = json.loads(source_report.read_text(encoding="utf-8"))
            capacity = source_data.get("userdata_capacity_bytes")
            geometry = source_data.get("userdata_geometry")
        except (OSError, ValueError, TypeError):
            pass
    return {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact_kind": "android-sparse-transport",
        "device_access": False,
        "flashable": False,
        "raw": {
            "path": relative(raw),
            "file_bytes": raw.stat().st_size,
            "sha256": raw_sha,
        },
        "sparse": {
            "path": relative(sparse),
            "sha256": sparse_sha,
            **facts,
        },
        "expanded_sha256": expanded_sha,
        "expands_byte_for_byte": raw_sha == expanded_sha,
        "userdata_capacity_bytes": capacity,
        "userdata_geometry": geometry,
        "notes": [
            "Sparse encoding changes fastboot transport only; it does not change SHNGROOT offsets or contents.",
            "The userdata GPT geometry recorded in userdata-root.json is provisional until read-only phone GPT evidence confirms it.",
            "This report does not authorize or perform a fastboot write.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--sparse", type=Path, default=DEFAULT_SPARSE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--check-only", action="store_true", help="validate an existing sparse file")
    parser.add_argument("--force", action="store_true", help="rebuild the sparse file if it already exists")
    args = parser.parse_args()
    raw = args.raw.resolve()
    sparse = args.sparse.resolve()
    report_path = args.report.resolve()
    if not raw.is_file():
        raise SystemExit(f"raw userdata image not found: {raw}")
    converter = load_upstream()
    if not sparse.is_file() or args.force:
        if args.check_only:
            raise SystemExit(f"sparse userdata image not found: {sparse}")
        sparse.parent.mkdir(parents=True, exist_ok=True)
        blocks, chunks = converter.convert(raw, sparse)
        print(f"created {sparse} ({blocks} blocks, {chunks} chunks)")
    facts = sparse_facts(sparse)
    if facts["expanded_bytes"] != raw.stat().st_size:
        raise SystemExit("sparse expanded size does not equal raw userdata size")
    raw_sha = converter.sha256_file(raw)
    expanded_sha = converter.expand_hash(sparse, facts["total_blocks"])
    sparse_sha = converter.sha256_file(sparse)
    if raw_sha != expanded_sha:
        raise SystemExit("sparse expansion SHA-256 differs from raw userdata SHA-256")
    report = build_report(raw, sparse, facts, raw_sha, expanded_sha, sparse_sha)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"raw sha256      {raw_sha}")
    print(f"expanded sha256 {expanded_sha}")
    print(f"sparse sha256   {sparse_sha}")
    print(f"sparse bytes    {facts['file_bytes']}")
    print(f"chunks          {facts['total_chunks']} ({facts['chunk_counts']})")
    print(f"wrote report    {report_path}")
    print("OK: sparse image expands byte-for-byte to the raw SHNGROOT image")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
