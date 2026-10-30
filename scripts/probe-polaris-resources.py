#!/usr/bin/env python3
"""Validate the extracted Polaris DTB resource contract without MMIO.

This is a host-side evidence gate.  It consumes the JSON produced from the
stock Xiaomi DTB bundle and checks that every Polaris variant describes the
same SDM845 windows used by the future Darwin driver ports.  It never opens a
device, maps a register, or talks to fastboot/adb.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = PROJECT / "research" / "polaris-dtb-resources.json"

EXPECTED = {
    "gpu": ("qcom,kgsl-3d0@5000000", "qcom,kgsl-3d0", [0x05000000, 0x40000, 0x05061000, 0x800, 0x0509E000, 0x1000], [0, 300, 0]),
    "gmu": ("qcom,gmu", "qcom,gpu-gmu", [0x0506A000, 0x30000, 0x0B200000, 0x300000], [0, 304, 0, 0, 305, 0]),
    "smmu": ("arm,smmu-kgsl@5040000", "qcom,smmu-v2", [0x05040000, 0x10000], None),
    "display": ("qcom,mdss_mdp@ae00000", "qcom,sde-kms", [0x0AE00000, 0x81D40, 0x0AEB0000, 0x2008, 0x0AEAC000, 0xF0], [0, 83, 0]),
    "ufs": ("ufshc@1d84000", "qcom,ufshc", [0x01D84000, 0x2500], [0, 265, 0]),
}


def node_map(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["name"]: node for node in entry.get("nodes", []) if "name" in node}


def compatible(node: dict[str, Any], value: str) -> bool:
    return value in node.get("compatible", [])


def check_entry(entry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    nodes = node_map(entry)
    for role, (name, compat, reg, interrupts) in EXPECTED.items():
        node = nodes.get(name)
        if node is None:
            errors.append(f"{role}: missing node {name}")
            continue
        if not compatible(node, compat):
            errors.append(f"{role}: {name} missing compatible {compat}")
        if node.get("reg") != reg:
            errors.append(f"{role}: {name} register window mismatch")
        if interrupts is not None and node.get("interrupts") != interrupts:
            errors.append(f"{role}: {name} interrupt tuple mismatch")

    bt = next((node for node in nodes.values() if node.get("name") == "bt_wcn3990"), None)
    if bt is None or not compatible(bt, "qca,wcn3990"):
        errors.append("bluetooth: qca,wcn3990 node missing")

    wlan = next((node for node in nodes.values() if node.get("name", "").startswith("wlan_fw_region@")), None)
    if wlan is None or wlan.get("reg") != [0, 0x8E300000, 0, 0x100000]:
        errors.append("wifi: wlan_fw_region 0x8e300000/0x100000 mismatch")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=DEFAULT_INPUT,
                        help="polaris-dtb-resources.json")
    parser.add_argument("-o", "--output", type=Path,
                        help="write the JSON report here")
    args = parser.parse_args()
    source = args.input.resolve()
    if not source.is_file():
        parser.error(f"resource JSON not found: {source}")
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        parser.error("resource JSON must be a non-empty list")

    all_errors: list[dict[str, Any]] = []
    for entry in data:
        errors = check_entry(entry)
        if errors:
            all_errors.append({"index": entry.get("index"), "errors": errors})
    models = sorted({model for entry in data for model in entry.get("model", [])})
    report = {
        "schema": 1,
        "source": source.name,
        "variant_count": len(data),
        "indices": [entry.get("index") for entry in data],
        "models": models,
        "checks": {
            "all_variants_match_sdm845_contract": not all_errors,
            "mmio_performed": False,
            "device_access": False,
        },
        "errors": all_errors,
        "shared_windows": {
            role: {"name": spec[0], "compatible": spec[1], "reg": spec[2], "interrupts": spec[3]}
            for role, spec in EXPECTED.items()
        },
        "wifi": {"reserved_memory_base": 0x8E300000, "reserved_memory_size": 0x100000},
    }
    output = args.output.resolve() if args.output else None
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if all_errors:
        for item in all_errors:
            print(f"FAIL index={item['index']}: {'; '.join(item['errors'])}")
        raise SystemExit(1)
    print(f"PASS: {len(data)} Polaris DTB variants match the SDM845 resource contract")
    print("No device access or MMIO was performed")


if __name__ == "__main__":
    main()
