#!/usr/bin/env python3
"""Check the Polaris mockfs/prelink root-stage inputs without touching a device.

This gate deliberately distinguishes host-side prerequisites from a bootable
root.  A passing report means that the source tree is ready for a Darwin 23
build attempt; it does not mean that a kernel, userdata image, or phone-tested
payload exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tomllib


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def macho_facts(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) < 32 or struct.unpack_from("<I", data, 0)[0] != 0xFEEDFACF:
        return {"mach_o_arm64": False, "bytes": len(data)}
    magic, cputype, cpusubtype, filetype, commands, sizeofcmds, flags, reserved = struct.unpack_from(
        "<8I", data, 0
    )
    return {
        "mach_o_arm64": cputype == 0x0100000C,
        "bytes": len(data),
        "cputype": cputype,
        "cpusubtype": cpusubtype,
        "filetype": filetype,
        "load_commands": commands,
        "load_commands_bytes": sizeofcmds,
        "flags": flags,
        "reserved": reserved,
    }


def shngroot_facts(path: Path) -> dict[str, object]:
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


def check(root: Path, upstream: Path, inputs: Path) -> dict[str, object]:
    board = tomllib.loads((root / "board.toml").read_text(encoding="utf-8"))
    userdata = board.get("userdata", {})
    defconfig = root / "configs" / "polaris_prelink_defconfig"
    config_text = defconfig.read_text(encoding="utf-8") if defconfig.is_file() else ""
    required_config = {
        "XNU_BUILD_ARCHIVES": "CONFIG_XNU_BUILD_ARCHIVES=y",
        "XNU_SOURCE_MOCKFS": "CONFIG_XNU_SOURCE_MOCKFS=y",
        "XNU_TRUST_CACHE_RUNTIME": "CONFIG_XNU_TRUST_CACHE_RUNTIME=y",
        "XNU_NATIVE_UFS": "CONFIG_XNU_NATIVE_UFS=n",
        "XNU_NATIVE_ADRENO": "CONFIG_XNU_NATIVE_ADRENO=n",
    }
    config_checks = {name: value in config_text for name, value in required_config.items()}

    patch_names = [
        "mockfs-intermediate-lookup.patch",
        "mockfs-memory-device-width.patch",
        "mockfs-statfs.patch",
        "mockfs-test-file.patch",
        "mockfs-typed-allocation.patch",
    ]
    patch_dir = upstream / "patches" / "xnu"
    patches = {name: (patch_dir / name).is_file() for name in patch_names}

    kernel = inputs / "kernelcache.release.ipad7.arm64.macho"
    # Prefer artifacts under the repository being checked.  The older local
    # workspace layout kept ``out`` beside ``device-repo``; retain that path
    # only as a compatibility fallback for existing local evidence.
    userdata_image = root / "out" / "polaris" / "userdata" / "userdata-root.img"
    if not userdata_image.is_file():
        legacy_userdata = PROJECT / "out" / "polaris" / "userdata" / "userdata-root.img"
        if legacy_userdata.is_file():
            userdata_image = legacy_userdata
    trust_caches = sorted(inputs.rglob("*.dmg.trustcache"))
    pinned_dmgs = [name for name in board.get("ipsw", {}).get("sha256", {}) if name.endswith(".dmg")]
    # The restore manifest calls these opaque 044-* names; their semantic
    # roles are determined by the board recipe, so do not rely on an "OS"
    # substring in the filename.
    os_dmg = sorted(path for name in pinned_dmgs[:1] for path in inputs.rglob(name))
    system_dmg = sorted(path for name in pinned_dmgs[1:2] for path in inputs.rglob(name))
    toolchain = {
        "clang": shutil.which("clang") is not None,
        "clang++": shutil.which("clang++") is not None,
        "xcrun": shutil.which("xcrun") is not None,
        "wsl": shutil.which("wsl.exe") is not None,
    }

    archive_entries = board.get("kernel", {}).get("archives", [])
    report: dict[str, object] = {
        "board": board.get("board", {}).get("name"),
        "target": "polaris / Darwin 23 / iPadOS 17 ABI research",
        "device_access": False,
        "mockfs": {
            "archive_recipe_present": "build-mockfs-fixture.py" in archive_entries,
            "source_builder_present": (upstream / "scripts" / "build-mockfs-fixture.py").is_file(),
            "defconfig": config_checks,
            "patches": patches,
        },
        "kernelcache": {
            "path": str(kernel),
            "present": kernel.is_file(),
            "facts": macho_facts(kernel) if kernel.is_file() else None,
            "sha256": sha256(kernel) if kernel.is_file() else None,
        },
        "trust_cache": {
            "files": [
                {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
                for path in trust_caches
            ],
            "present": bool(trust_caches),
        },
        "root_images": {
            "os_dmg_present": bool(os_dmg),
            "system_os_dmg_present": bool(system_dmg),
            "os_dmg_paths": [str(path) for path in os_dmg],
            "system_os_dmg_paths": [str(path) for path in system_dmg],
        },
        "userdata_geometry": {
            "first_lba": userdata.get("first_lba"),
            "last_lba": userdata.get("last_lba"),
            "lba_bytes": userdata.get("lba_bytes"),
            "provisional": True,
        },
        "userdata_artifact": {
            "path": str(userdata_image),
            "present": userdata_image.is_file(),
            "facts": shngroot_facts(userdata_image),
        },
        "host_toolchain": toolchain,
    }

    blockers: list[str] = []
    if not report["mockfs"]["archive_recipe_present"]:
        blockers.append("board.toml does not schedule build-mockfs-fixture.py")
    if not report["mockfs"]["source_builder_present"]:
        blockers.append("UniXNU build-mockfs-fixture.py is missing")
    blockers.extend(
        f"prelink defconfig missing {name}" for name, ok in config_checks.items() if not ok
    )
    blockers.extend(f"missing XNU patch {name}" for name, ok in patches.items() if not ok)
    if not kernel.is_file():
        blockers.append("decoded iPadOS 17 arm64 kernelcache is missing")
    elif not report["kernelcache"]["facts"]["mach_o_arm64"]:
        blockers.append("kernelcache input is not a plain arm64 Mach-O")
    if not trust_caches:
        blockers.append("no trust-cache input is present")
    if not os_dmg or not system_dmg:
        blockers.append("OS/SystemOS DMGs are absent; no userdata root can be assembled")
    if not all(toolchain.values()):
        missing = ", ".join(name for name, ok in toolchain.items() if not ok and name != "wsl")
        if missing:
            blockers.append(f"host compiler tools missing: {missing}")

    report["blockers"] = blockers
    prelink_blockers = []
    if not kernel.is_file() or not report["kernelcache"]["facts"]["mach_o_arm64"]:
        prelink_blockers.append("a decoded arm64 kernelcache is required")
    if not all(toolchain.get(name, False) for name in ("clang", "clang++", "xcrun")):
        prelink_blockers.append("Darwin 23 compiler tools are unavailable on this host")
    report["ready_for_prelink_build_attempt"] = not prelink_blockers
    report["prelink_blockers"] = prelink_blockers
    report["ready_for_userdata_build"] = bool(os_dmg and system_dmg)
    report["ready_for_phone_boot"] = False
    report["reason_phone_boot_false"] = (
        "A source build, root image, trust chain, firmware path and hardware validation "
        "are still required; this report performs no device access."
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--upstream", type=Path, default=PROJECT / "upstream" / "UniXNU")
    parser.add_argument("--inputs", type=Path, default=PROJECT / "inputs" / "ipsw")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = check(args.root.resolve(), args.upstream.resolve(), args.inputs.resolve())
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if not report["blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
