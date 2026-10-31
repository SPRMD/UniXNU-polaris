#!/usr/bin/env python3
"""Verify the pinned iPadOS OS/SystemOS inputs before root assembly.

The IPSW fetcher already downloads members from Apple's archive, but the
stage builder should also leave an explicit, reproducible hash report next to
the files it consumes. This checker reads the two SHA-256 pins from
``board.toml`` and searches a supplied artifact tree without copying or
modifying any input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tomllib


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def find_unique(root: Path, name: str) -> Path:
    matches = sorted(path for path in root.rglob(name) if path.is_file())
    if not matches:
        raise SystemExit(f"missing pinned IPSW member: {name} under {root}")
    if len(matches) != 1:
        rendered = ", ".join(str(path) for path in matches)
        raise SystemExit(f"ambiguous IPSW member {name}: {rendered}")
    return matches[0]


def verify(root: Path, board_file: Path) -> dict[str, object]:
    board = tomllib.loads(board_file.read_text(encoding="utf-8"))
    pins = board.get("ipsw", {}).get("sha256", {})
    required = ("044-76040-038.dmg", "044-76034-038.dmg")
    missing_pins = [name for name in required if not isinstance(pins.get(name), str)]
    if missing_pins:
        raise SystemExit("board.toml is missing SHA-256 pins: " + ", ".join(missing_pins))
    members: dict[str, object] = {}
    for name in required:
        path = find_unique(root, name)
        actual = digest(path)
        expected = str(pins[name]).lower()
        if actual != expected:
            raise SystemExit(f"SHA-256 mismatch for {name}: expected {expected}, got {actual}")
        members[name] = {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": actual,
            "pin": expected,
        }
    return {
        "schema": 1,
        "board": board.get("board", {}).get("name", ""),
        "product": board.get("ipsw", {}).get("product", ""),
        "version": board.get("ipsw", {}).get("version", ""),
        "build": board.get("ipsw", {}).get("build", ""),
        "members": members,
        "verified": True,
        "device_access": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True,
                        help="artifact tree containing the fetched IPSW members")
    parser.add_argument("--board", type=Path,
                        default=Path(__file__).resolve().parents[1] / "board.toml")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    board = args.board.resolve()
    if not root.is_dir():
        parser.error(f"input root not found: {root}")
    if not board.is_file():
        parser.error(f"board file not found: {board}")
    report = verify(root, board)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print("PASS: iPadOS OS/SystemOS SHA-256 pins verified")
    for name, member in report["members"].items():
        print(f"  {name}: {member['sha256']}")
    print("No device access was performed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
