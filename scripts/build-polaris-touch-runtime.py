#!/usr/bin/env python3
"""Compile the opt-in Polaris GPIO33/34 RMI4 runtime transport.

The source is a small BSD-side kernel component because the Darwin 23 IOKit
contract service is not a QUPv3 bus driver.  It is linked as a force-loaded
archive, but it does nothing unless the runtime boot argument is present.
"""

from __future__ import annotations

import json
from pathlib import Path
import struct
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    tree = ROOT
    record = tree / "build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/bsd/DEVELOPMENT/bsd_init.o.json"
    if not record.is_file():
        raise SystemExit(f"missing Darwin C compile record: {record}")
    data = json.loads(record.read_text(encoding="utf-8").strip().rstrip(","))
    source = tree / "drivers/PolarisSynapticsTouch/PolarisTouchRuntime.c"
    out = tree / "build/polaris-touch-runtime"
    out.mkdir(parents=True, exist_ok=True)
    object_path = out / "PolarisTouchRuntime.o"
    arguments = data["arguments"]
    command: list[str] = []
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value == data["file"]:
            command.append(str(source))
        elif value == "-o":
            command.extend(["-o", str(object_path)])
            index += 1
        elif value == "-Xclang" and index + 1 < len(arguments) and arguments[index + 1].startswith("-W"):
            index += 1
        elif not value.startswith("-W"):
            command.append(value)
        index += 1
    command.extend(["-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                    "-I", str(source.parent)])
    (out / "compile-command.json").write_text(
        json.dumps(command, indent=2) + "\n", encoding="utf-8"
    )
    result = subprocess.run(command, cwd=data["directory"], capture_output=True,
                            text=True)
    (out / "compile.log").write_text(result.stdout + result.stderr,
                                     encoding="utf-8")
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    raw = object_path.read_bytes()
    if struct.unpack_from("<4I", raw) != (0xfeedfacf, 0x100000C, 0, 1):
        raise SystemExit("PolarisTouchRuntime: expected a plain ARM64 Mach-O object")
    archive = out / "libPolarisTouchRuntime.a"
    archive.unlink(missing_ok=True)
    subprocess.run(["xcrun", "ar", "rcs", str(archive), str(object_path)],
                   check=True)
    print(f"PolarisTouchRuntime: ARM64/iOS 17 archive built at {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
