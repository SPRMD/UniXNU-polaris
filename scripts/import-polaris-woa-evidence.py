#!/usr/bin/env python3
"""Build a metadata-only Polaris WOA/vendor evidence manifest.

The WOA-Drivers tree contains Windows driver binaries and vendor firmware.  A
Windows ``.sys``/``.dll``/firmware file is never a Darwin driver, so this tool
records names, paths, sizes and classifications only.  It does not copy or
embed any binary input and it never accesses a phone.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WOA = ROOT.parent.parent / "external" / "WOA-Drivers"
DEFAULT_WOA_POLARIS = ROOT.parent.parent / "research" / "external" / "woa-polaris"
DEFAULT_VENDOR = ROOT.parent.parent / "proprietary" / "polaris-vendor-evidence"

SUBSYSTEM_PATHS = {
    "touch": ["components/SDM845/Device/Xiaomi/Polaris/SynapticsTouch"],
    "camera": [
        "components/SDM845/Device/Xiaomi/Polaris/Camera/RearSensor",
        "components/SDM845/Platform/Camera",
    ],
    "gpu": ["components/SDM845/Device/Xiaomi/GPU"],
    "wifi": ["components/SDM845/Device/Generic/WLAN"],
    "bluetooth": ["components/SDM845/Platform/Bluetooth/UART"],
    "battery": ["components/SDM845/Platform/FG/BattMgr"],
    "gpio": ["components/SDM845/Platform/GPIO"],
    "nfc": ["components/AnySoC/NFC"],
}

BINARY_SUFFIXES = {
    ".sys", ".dll", ".exe", ".cat", ".bin", ".tlv", ".b3c", ".mbn",
    ".elf", ".fw", ".fw2", ".cab", ".msi",
}

REFERENCE_SUFFIXES = {
    ".inf_", ".inf", ".txt", ".json", ".xml", ".cfg", ".ini", ".acdb",
    ".qwsp", ".md", ".rst",
}


def sha256_file(path: Path) -> str | None:
    """Return a content digest without embedding the source document."""
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_polaris_status(path: Path) -> dict[str, dict[str, Any]]:
    """Parse the WOA Polaris support checklist as evidence only.

    The checklist is useful for deciding which board facts are worth porting,
    but its Windows drivers are never treated as Darwin implementations.  Keep
    the parser deliberately small: it records the checkbox state and the
    human-readable label, while leaving all Darwin readiness gates untouched.
    """
    if not path.is_file():
        return {}
    status: dict[str, dict[str, Any]] = {}
    pattern = re.compile(r"^\s*-\s*\[([ xX])\]\s+(.+?)\s*$")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        checked = match.group(1).lower() == "x"
        label = re.sub(r"\s+```.*$", "", match.group(2)).strip()
        # Keep the original label in the record and use a stable key for tools.
        key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        if not key:
            continue
        status[key] = {"label": label, "working_on_windows": checked}
    return status


def git_revision(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def classify(path: Path) -> tuple[str, bool]:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix in BINARY_SUFFIXES or name.endswith(".inf_") is False and not suffix:
        return "vendor-binary-or-firmware", False
    if suffix in REFERENCE_SUFFIXES:
        return "configuration-or-reference", False
    return "unclassified-input", False


def relative_label(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def collect_files(root: Path, paths: list[str], *, label: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for relative in paths:
        directory = root / Path(relative)
        if not directory.is_dir():
            continue
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            classification, darwin_reusable = classify(path)
            files.append({
                "path": f"{label}/{relative_label(path, root)}",
                "name": path.name,
                "bytes": path.stat().st_size,
                "classification": classification,
                "darwin_reusable": darwin_reusable,
                "copied": False,
            })
    return files


def subsystem_note(name: str) -> dict[str, Any]:
    notes: dict[str, dict[str, Any]] = {
        "touch": {
            "hardware": "Synaptics RMI4/S3708 (WOA) and legacy S3330 evidence",
            "darwin_status": "protocol/reference-only",
            "firmware_candidates": ["SynapticsTouch.sys"],
        },
        "camera": {
            "hardware": "Sony IMX363 rear sensor; Qualcomm SDM845 camera stack",
            "darwin_status": "reference-only",
            "firmware_candidates": ["com.qti.sensormodule.imx363.bin", "CAMERA_ICP_AAAAAA.elf"],
        },
        "gpu": {
            "hardware": "Qualcomm Adreno 630 / SDM845",
            "darwin_status": "reference-only",
            "firmware_candidates": ["a630_gmu.bin", "a630_sqe.fw", "a630_zap.mdt"],
        },
        "wifi": {
            "hardware": "Qualcomm WCN3998 runtime / WCN3990 DT naming",
            "darwin_status": "reference-only",
            "firmware_candidates": ["bdwlan.bin", "bdwlan.*", "WCNSS_qcom_cfg.ini"],
        },
        "bluetooth": {
            "hardware": "Qualcomm WCN3998 Bluetooth over UART",
            "darwin_status": "reference-only",
            "firmware_candidates": ["crbtfw20.tlv", "crnv20.bin", "crnv21.bin"],
        },
        "battery": {
            "hardware": "PMI8998 / SDM845 fuel gauge",
            "darwin_status": "reference-only",
            "firmware_candidates": [],
        },
        "gpio": {
            "hardware": "Qualcomm SDM845 GPIO controller",
            "darwin_status": "reference-only",
            "firmware_candidates": [],
        },
        "nfc": {
            "hardware": "NXP PN553-class NFC (cross-device WOA reference)",
            "darwin_status": "cross-device reference-only",
            "firmware_candidates": [],
        },
    }
    return notes.get(name, {"darwin_status": "reference-only", "firmware_candidates": []})


def build_manifest(*, woa_root: Path | None = None,
                   woa_polaris_root: Path | None = None,
                   vendor_root: Path | None = None) -> dict[str, Any]:
    woa_root = woa_root.resolve() if woa_root else DEFAULT_WOA.resolve()
    woa_polaris_root = woa_polaris_root.resolve() if woa_polaris_root else DEFAULT_WOA_POLARIS.resolve()
    vendor_root = vendor_root.resolve() if vendor_root else DEFAULT_VENDOR.resolve()
    status_file = woa_polaris_root / "guide" / "status.md"
    polaris_status = parse_polaris_status(status_file)

    subsystems: dict[str, Any] = {}
    for name, paths in SUBSYSTEM_PATHS.items():
        files = collect_files(woa_root, paths, label="external/WOA-Drivers") if woa_root.is_dir() else []
        entry = subsystem_note(name)
        entry.update({
            "source": "edk2-porting/WOA-Drivers",
            "source_revision": git_revision(woa_root),
            "files": files,
            "available": bool(files),
            "copied": False,
            "darwin_driver": False,
        })
        subsystems[name] = entry

    vendor_files = []
    if vendor_root.is_dir():
        for path in sorted(p for p in vendor_root.rglob("*") if p.is_file()):
            classification, darwin_reusable = classify(path)
            vendor_files.append({
                "path": f"proprietary/polaris-vendor-evidence/{relative_label(path, vendor_root)}",
                "name": path.name,
                "bytes": path.stat().st_size,
                "classification": classification,
                "darwin_reusable": darwin_reusable,
                "copied": False,
            })

    return {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "board": "xiaomi,polaris",
        "soc": "Qualcomm SDM845",
        "policy": {
            "metadata_only": True,
            "copy_vendor_binaries": False,
            "android_or_windows_binaries_are_darwin_drivers": False,
            "flashable": False,
        },
        "sources": {
            "woa_drivers": {
                "path": "../../external/WOA-Drivers",
                "present": woa_root.is_dir(),
                "revision": git_revision(woa_root),
            },
            "woa_polaris_docs": {
                "path": "research/external/woa-polaris",
                "present": woa_polaris_root.is_dir(),
                "revision": git_revision(woa_polaris_root),
                "status_file": "guide/status.md",
                "status_sha256": sha256_file(status_file),
                "status_features": polaris_status,
            },
            "vendor_evidence": {
                "path": "proprietary/polaris-vendor-evidence",
                "present": vendor_root.is_dir(),
                "file_count": len(vendor_files),
            },
        },
        "subsystems": subsystems,
        "woa_polaris_status": {
            "source": "woa-polaris/guide/status.md",
            "sha256": sha256_file(status_file),
            "features": polaris_status,
            "darwin_driver": False,
            "note": "Windows-on-ARM checklist evidence only; it does not qualify a Darwin driver or a flashable package.",
        },
        "vendor_evidence_files": vendor_files,
        "darwin_porting_rule": "Use names and protocol/resource facts as evidence. Implement a board-owned Darwin transport and validate on Polaris before enabling it.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--woa-root", type=Path, default=DEFAULT_WOA)
    parser.add_argument("--woa-polaris-root", type=Path, default=DEFAULT_WOA_POLARIS)
    parser.add_argument("--vendor-root", type=Path, default=DEFAULT_VENDOR)
    parser.add_argument("--output", type=Path, default=ROOT / "research" / "polaris-woa-evidence.json")
    args = parser.parse_args()
    manifest = build_manifest(woa_root=args.woa_root, woa_polaris_root=args.woa_polaris_root,
                              vendor_root=args.vendor_root)
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
    total = sum(len(v["files"]) for v in manifest["subsystems"].values())
    print(f"wrote metadata-only WOA evidence manifest: {args.output.resolve()} ({total} WOA files; copied=0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
