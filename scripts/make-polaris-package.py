#!/usr/bin/env python3
"""Assemble a guarded Polaris UniXNU package.

The output is deliberately useful before the port is flashable: it contains
the exact ESP tree, build reports, driver contract and hashes, together with a
one-click command that refuses to write a phone while any required gate is
open.  The refusal is part of the package contract.  A package becomes
flashable only when a prelinked kernel, a qualified firmware image, a complete
userdata root and every required Polaris subsystem have all been verified.

This script never talks to adb/fastboot and never changes a device.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import textwrap
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_fact(path: Path, *, package_root: Path | None = None) -> dict[str, Any]:
    fact: dict[str, Any] = {"present": path.exists(), "kind": "file" if path.is_file() else ("directory" if path.is_dir() else None)}
    if package_root is not None:
        try:
            fact["path"] = path.resolve().relative_to(package_root.resolve()).as_posix()
        except ValueError:
            fact["path"] = str(path)
    else:
        fact["path"] = str(path)
    if path.is_file():
        fact["bytes"] = path.stat().st_size
        fact["sha256"] = sha256(path)
    return fact


def load_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    contract_path = ROOT / "research" / "polaris-hardware-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    validator_path = ROOT / "scripts" / "check-polaris-driver-contract.py"
    spec = importlib.util.spec_from_file_location("polaris_contract", validator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {validator_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return contract, module.validate(contract)


def kernel_facts(kernel: Path) -> dict[str, Any]:
    report_path = kernel.with_suffix(".json")
    result: dict[str, Any] = {
        "kernel": file_fact(kernel),
        "report": file_fact(report_path),
        "report_valid": False,
        "source_kernel": False,
        "prelinked_kernel": False,
    }
    if not kernel.is_file() or not report_path.is_file():
        return result
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return result
    result["report_data"] = report
    result["report_valid"] = report.get("kernel_sha256") == sha256(kernel)
    result["source_kernel"] = (
        result["report_valid"]
        and report.get("final_configured_link_passed") is True
        and report.get("original_components_prelinked") is False
    )
    result["prelinked_kernel"] = (
        result["report_valid"]
        and report.get("final_configured_link_passed") is True
        and report.get("original_components_prelinked") is True
    )
    return result


def copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def write_guarded_flash_cmd(path: Path) -> None:
    path.write_text(
        "@echo off\r\n"
        "setlocal EnableExtensions\r\n"
        "echo Polaris UniXNU guarded installer\r\n"
        "if not exist \"%~dp0manifest.json\" (echo Missing manifest.json& exit /b 2)\r\n"
        "where powershell.exe >nul 2>nul || (echo PowerShell is required.& exit /b 2)\r\n"
        "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File \"%~dp0flash.ps1\"\r\n"
        "exit /b %errorlevel%\r\n",
        encoding="ascii",
    )


def write_guarded_flash_ps1(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            r'''
            $ErrorActionPreference = 'Stop'
            $root = Split-Path -Parent $MyInvocation.MyCommand.Path
            $manifest = Get-Content -Raw -LiteralPath (Join-Path $root 'manifest.json') | ConvertFrom-Json
            if (-not [bool]$manifest.flashable) {
                Write-Error 'This package is evidence-only and is not flashable. Review manifest.json for the open gates.'
                exit 3
            }
            if (-not (Get-Command fastboot.exe -ErrorAction SilentlyContinue)) {
                Write-Error 'fastboot.exe was not found in PATH.'
                exit 4
            }
            $device = @( & fastboot.exe devices 2>$null | Where-Object { $_ -match '\S+\s+fastboot' } )
            if ($device.Count -ne 1) {
                Write-Error "Expected exactly one fastboot device; found $($device.Count)."
                exit 5
            }
            $product = (& fastboot.exe getvar product 2>&1 | Out-String)
            if ($product -notmatch 'product:\s*polaris') {
                Write-Error 'Connected device is not polaris.'
                exit 6
            }
            $userdata = $manifest.inputs.userdata.path
            if (-not $userdata) { Write-Error 'Manifest has no userdata image.'; exit 7 }
            $userdataPath = Join-Path $root $userdata
            if (-not (Test-Path -LiteralPath $userdataPath -PathType Leaf)) {
                Write-Error "Missing userdata image: $userdataPath"; exit 8
            }
            $firmwarePath = $null
            if ($manifest.inputs.firmware.path) {
                $candidate = Join-Path $root $manifest.inputs.firmware.path
                if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                    $firmwarePath = $candidate
                } elseif (Test-Path -LiteralPath $candidate -PathType Container) {
                    $firmwarePath = Get-ChildItem -LiteralPath $candidate -Recurse -File |
                        Where-Object { $_.Name -match '(^|-)boot[^/]*\.img$' -or $_.Name -eq 'boot-polaris.img' } |
                        Select-Object -First 1 -ExpandProperty FullName
                }
            }
            if (-not $firmwarePath) { Write-Error 'Manifest has no boot firmware image.'; exit 9 }
            Write-Host 'Flashing the qualified userdata image...'
            & fastboot.exe flash userdata $userdataPath
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            Write-Host 'Booting the qualified Polaris firmware...'
            & fastboot.exe boot $firmwarePath
            exit $LASTEXITCODE
            '''
        ).lstrip(),
        encoding="utf-8",
    )


def build_package(esp: Path, esp_image: Path, kernel: Path, output: Path,
                  *, firmware: Path | None = None,
                  userdata: Path | None = None,
                  device_validation: Path | None = None) -> dict[str, Any]:
    esp = esp.resolve()
    esp_image = esp_image.resolve()
    kernel = kernel.resolve()
    output = output.resolve()
    if not esp.is_dir():
        raise ValueError(f"ESP directory not found: {esp}")
    if not esp_image.is_file():
        raise ValueError(f"ESP image not found: {esp_image}")
    if not kernel.is_file():
        raise ValueError(f"kernel not found: {kernel}")

    contract, contract_report = load_contract()
    kfacts = kernel_facts(kernel)
    firmware = firmware.resolve() if firmware else None
    userdata = userdata.resolve() if userdata else None
    device_validation = device_validation.resolve() if device_validation else None

    blockers: list[str] = []
    if not kfacts["report_valid"]:
        blockers.append("kernel.macho is missing a matching kernel.json build report")
    if not kfacts["prelinked_kernel"]:
        blockers.append("kernel is not a verified prelinked Darwin userland kernel")
    if firmware is None or not firmware.exists():
        blockers.append("no qualified Polaris UEFI/boot firmware image was supplied")
    firmware_provenance: dict[str, Any] | None = None
    if firmware and firmware.exists():
        provenance_path = (firmware / "firmware-provenance.json") if firmware.is_dir() else firmware.with_name("firmware-provenance.json")
        if provenance_path.is_file():
            try:
                firmware_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                blockers.append("firmware provenance is not valid JSON")
        else:
            blockers.append("firmware provenance is missing")
        if firmware_provenance is not None and (
                firmware_provenance.get("board") != "xiaomi,polaris"
                or firmware_provenance.get("hardware_tested") is not True):
            blockers.append("firmware provenance does not attest a hardware-tested polaris image")
    if userdata is None or not userdata.is_file():
        blockers.append("no qualified SHNGROOT userdata image was supplied")
    if not contract_report["all_required_subsystems_verified"]:
        missing = sorted(set(contract_report["required_for_flash"]) - set(contract_report["verified"]))
        blockers.append("required hardware drivers are not verified: " + ", ".join(missing))
    if device_validation is None or not device_validation.is_file():
        blockers.append("no independent Polaris temporary-boot validation report was supplied")

    # Even a syntactically complete input set is not allowed to flash until a
    # human-reviewed validation report explicitly says the board was tested.
    validation_ok = False
    validation_report: dict[str, Any] | None = None
    if device_validation and device_validation.is_file():
        try:
            validation_report = json.loads(device_validation.read_text(encoding="utf-8"))
            validation_ok = (
                validation_report.get("board") == "xiaomi,polaris"
                and validation_report.get("hardware_tested") is True
                and validation_report.get("temporary_boot") is True
            )
        except (OSError, json.JSONDecodeError):
            blockers.append("device validation report is not valid JSON")
    if device_validation and device_validation.is_file() and not validation_ok:
        blockers.append("device validation report does not attest a temporary Polaris boot")

    flashable = not blockers
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    copy_tree(esp, output / "esp")
    shutil.copy2(esp_image, output / "esp.img")
    shutil.copy2(kernel, output / "kernel.macho")
    report = kernel.with_suffix(".json")
    if report.is_file():
        shutil.copy2(report, output / "kernel.json")
    firmware_target: Path | None = None
    if firmware and firmware.is_file():
        firmware_target = output / firmware.name
        shutil.copy2(firmware, firmware_target)
    elif firmware and firmware.is_dir():
        firmware_target = output / "firmware"
        copy_tree(firmware, firmware_target)
    if userdata and userdata.is_file():
        shutil.copy2(userdata, output / userdata.name)
    shutil.copy2(ROOT / "research" / "polaris-hardware-contract.json", output / "polaris-hardware-contract.json")
    shutil.copy2(ROOT / "research" / "polaris-driver-matrix.json", output / "polaris-driver-matrix.json")

    manifest: dict[str, Any] = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "board": "xiaomi,polaris",
        "variant": {"ram_gib": 6, "storage_gib": 128},
        "target": "UniXNU Darwin 23 / iPadOS 17 ABI research",
        "flashable": flashable,
        "safe_to_flash": flashable,
        "device_access": {"adb": False, "fastboot": False, "partition_writes": False},
        "inputs": {
            "esp": file_fact(output / "esp", package_root=output),
            "esp_image": file_fact(output / "esp.img", package_root=output),
            "kernel": file_fact(output / "kernel.macho", package_root=output),
            "firmware": file_fact(firmware_target, package_root=output) if firmware_target else {"present": False},
            "userdata": file_fact(output / userdata.name, package_root=output) if userdata and userdata.is_file() else {"present": False},
        },
        "kernel": kfacts,
        "driver_contract": contract_report,
        "device_validation": validation_report,
        "firmware_provenance": firmware_provenance,
        "blockers": blockers,
        "installer": {
            "generated": True,
            "commands": ["fastboot flash userdata <userdata>", "fastboot boot <firmware>"] if flashable else [],
            "guard": "manifest.flashable must be true and exactly one polaris fastboot device must be present",
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    write_guarded_flash_cmd(output / "flash.cmd")
    write_guarded_flash_ps1(output / "flash.ps1")

    entries: list[str] = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            entries.append(f"{sha256(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS").write_text("\n".join(entries) + "\n", encoding="ascii")
    (output / "README.txt").write_text(
        "This is a guarded Polaris UniXNU package.\n"
        f"flashable={str(flashable).lower()}\n"
        "Run flash.cmd only after reviewing manifest.json; the current build refuses to flash when any gate is open.\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--esp", type=Path, required=True)
    parser.add_argument("--esp-image", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--firmware", type=Path)
    parser.add_argument("--userdata", type=Path)
    parser.add_argument("--device-validation", type=Path)
    args = parser.parse_args()
    manifest = build_package(args.esp, args.esp_image, args.kernel, args.out,
                             firmware=args.firmware, userdata=args.userdata,
                             device_validation=args.device_validation)
    print(f"wrote guarded Polaris package: {args.out.resolve()}")
    print(f"flashable={manifest['flashable']}")
    for blocker in manifest["blockers"]:
        print(f"BLOCKED: {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
