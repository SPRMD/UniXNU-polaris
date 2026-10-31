#!/usr/bin/env python3
"""Derive a privacy-filtered hardware fact report from a MIUI adb capture.

The capture helper intentionally stores raw logs for the owner, but those logs
can contain serial numbers, IMEIs, network addresses and input traces.  This
tool reads only an allow-list of property keys and component names.  It never
reads ``input-events.txt``, ``logcat-all.txt`` or ``dropbox.txt`` and never
copies a raw line into the report.  The output is board evidence for driver
planning, not proof that a Darwin driver works.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


GETPROP_KEYS = {
    "ro.board.platform",
    "ro.boot.baseband",
    "ro.boot.bootdevice",
    "ro.boot.hardware",
    "ro.boot.hwc",
    "ro.boot.hwlevel",
    "ro.boot.hwversion",
    "ro.boot.secureboot",
    "ro.boot.verifiedbootstate",
    "ro.build.product",
    "ro.build.version.release",
    "ro.build.version.sdk",
    "ro.bluetooth.library_name",
    "ro.hardware.egl",
    "ro.hardware.nfc_nci",
    "ro.hardware.vulkan",
}

SERVICE_KEYS = {
    "init.svc.bluetooth",
    "init.svc.cameraserver",
    "init.svc.gpu",
    "init.svc.nqnfc_1_1_hal_service",
    "init.svc.surfaceflinger",
    "init.svc.wificond",
    "init.svc.wpa_supplicant",
}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_getprop(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    properties: dict[str, str] = {}
    services: dict[str, str] = {}
    pattern = re.compile(r"^\[([^\]]+)\]: \[([^\]]*)\]$")
    for line in read_text(path).splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        key, value = match.groups()
        if key in GETPROP_KEYS:
            properties[key] = value
        elif key in SERVICE_KEYS:
            services[key.removeprefix("init.svc.")] = value
    return properties, services


def count_matches(text: str, patterns: dict[str, tuple[str, ...]]) -> dict[str, bool]:
    folded = text.casefold()
    return {name: any(item.casefold() in folded for item in needles)
            for name, needles in patterns.items()}


def first_resolution(text: str) -> str | None:
    # Accept common dumpsys forms without retaining any surrounding line.
    for pattern in (r"\b(\d{3,5})x(\d{3,5})\b",
                    r"width[=:](\d{3,5}).*?height[=:](\d{3,5})"):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return f"{match.group(1)}x{match.group(2)}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="one runtime-captures/<timestamp> directory")
    parser.add_argument("-o", "--output", type=Path,
                        help="JSON output (default: <capture>/runtime-facts.json)")
    args = parser.parse_args()
    capture = args.capture.resolve()
    if not capture.is_dir():
        parser.error(f"capture directory does not exist: {capture}")

    props, services = parse_getprop(capture / "getprop.txt")
    display = read_text(capture / "dumpsys-display-input.txt")
    wireless = read_text(capture / "dumpsys-wireless-nfc.txt")
    sensors_camera = read_text(capture / "dumpsys-sensors-camera.txt")
    bus = read_text(capture / "bus-devices.txt")
    vendor = read_text(capture / "vendor-hardware-files.txt")
    power = read_text(capture / "power-supply.txt")

    components = count_matches(
        "\n".join((display, wireless, sensors_camera, bus, vendor)),
        {
            "touch_synaptics_dsx": ("synaptics_dsx",),
            "wifi_qualcomm": ("wificond", "wlan", "qca", "wcn3990"),
            "bluetooth_qualcomm": ("bluetooth", "wcn3990", "libbluetooth_qti"),
            "nfc_nxp": ("nfc", "nxp", "nqnfc"),
            "camera_service": ("cameraserver", "camera", "mm-qcamera"),
            "adreno_gpu": ("adreno", "kgsl", "gpu"),
            "ufs_bootdevice": ("ufshc", "1d84000"),
        },
    )

    power_names = sorted({
        match.group(1)
        for match in re.finditer(r"^==== /sys/class/power_supply/([A-Za-z0-9_.-]+)\s*$",
                                 power, re.MULTILINE)
    })
    bootdevice = props.get("ro.boot.bootdevice", "")
    if "ufshc" in bootdevice or "1d84000" in bootdevice:
        components["ufs_bootdevice"] = True
    report = {
        "schema": 1,
        "source": "MIUI adb read-only capture",
        "capture": capture.name,
        "properties": props,
        "services": services,
        "hardware_hints": {
            "display_resolution": first_resolution(display),
            "components": components,
            "bootdevice": bootdevice or None,
            "power_supply_names": power_names,
            "vendor_firmware_listing_present": bool(vendor.strip()),
        },
        "privacy": {
            "raw_lines_copied": False,
            "input_events_used": False,
            "logcat_used": False,
            "dropbox_used": False,
            "telephony_or_serial_identifiers_emitted": False,
        },
        "excluded_files": ["input-events.txt", "logcat-all.txt", "dropbox.txt"],
        "interpretation": {
            "status": "evidence-only",
            "warning": "These facts guide a board driver port; they do not prove a Darwin driver or authorize flashing.",
        },
    }
    output = (args.output or capture / "runtime-facts.json").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote privacy-filtered runtime facts: {output}")
    print("input-events/logcat/dropbox were excluded; no device access was performed")


if __name__ == "__main__":
    main()
