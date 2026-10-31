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
            $sumsPath = Join-Path $root 'SHA256SUMS'
            if (-not (Test-Path -LiteralPath $sumsPath -PathType Leaf)) {
                Write-Error 'Missing SHA256SUMS; refusing to flash.'
                exit 2
            }
            foreach ($line in Get-Content -LiteralPath $sumsPath) {
                if ([string]::IsNullOrWhiteSpace($line)) { continue }
                if ($line -notmatch '^(?<hash>[0-9a-fA-F]{64})  (?<relative>.+)$') {
                    Write-Error "Invalid SHA256SUMS line: $line"
                    exit 2
                }
                $relative = $Matches.relative
                if ([IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[\\/])\.\.([\\/]|$)') {
                    Write-Error "Unsafe checksum path: $relative"
                    exit 2
                }
                $target = Join-Path $root ($relative -replace '/', [IO.Path]::DirectorySeparatorChar)
                if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
                    Write-Error "Checksum target is missing: $relative"
                    exit 2
                }
                $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($actual -ne $Matches.hash.ToLowerInvariant()) {
                    Write-Error "SHA-256 mismatch: $relative"
                    exit 2
                }
            }
            # SHA256SUMS protects the package file set; the manifest input
            # records protect the files that the installer is about to use.
            # Check both independently before looking for a device.
            if ($null -eq $manifest.inputs) {
                Write-Error 'Manifest has no inputs object; refusing to flash.'
                exit 2
            }
            foreach ($property in $manifest.inputs.PSObject.Properties) {
                $fact = $property.Value
                if ($null -eq $fact -or -not [bool]$fact.present) { continue }
                $relative = [string]$fact.path
                if ([string]::IsNullOrWhiteSpace($relative) -or
                    [IO.Path]::IsPathRooted($relative) -or
                    $relative -match '(^|[\\/])\.\.([\\/]|$)' -or
                    $relative -match '^[A-Za-z]:') {
                    Write-Error "Unsafe manifest input path: $relative"
                    exit 2
                }
                $target = Join-Path $root ($relative -replace '/', [IO.Path]::DirectorySeparatorChar)
                if (-not (Test-Path -LiteralPath $target)) {
                    Write-Error "Manifest input is missing: $($property.Name) -> $relative"
                    exit 2
                }
                if ($fact.sha256 -and (Test-Path -LiteralPath $target -PathType Leaf)) {
                    $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
                    if ($actual -ne ([string]$fact.sha256).ToLowerInvariant()) {
                        Write-Error "Manifest input SHA-256 mismatch: $($property.Name)"
                        exit 2
                    }
                }
            }
            Write-Host 'SHA-256 package verification passed.'
            if ($null -eq $manifest.safe_to_flash -or
                [bool]$manifest.safe_to_flash -ne [bool]$manifest.flashable) {
                Write-Error 'Manifest flash gates are inconsistent; refusing to flash.'
                exit 3
            }
            if (-not [bool]$manifest.flashable) {
                Write-Error 'This package is evidence-only and is not flashable. Review manifest.json for the open gates.'
                exit 4
            }
            if (-not (Get-Command fastboot.exe -ErrorAction SilentlyContinue)) {
                Write-Error 'fastboot.exe was not found in PATH.'
                exit 5
            }
            $device = @( & fastboot.exe devices 2>$null | Where-Object { $_ -match '\S+\s+fastboot' } )
            if ($device.Count -ne 1) {
                Write-Error "Expected exactly one fastboot device; found $($device.Count)."
                exit 6
            }
            $product = (& fastboot.exe getvar product 2>&1 | Out-String)
            if ($product -notmatch 'product:\s*polaris') {
                Write-Error 'Connected device is not polaris.'
                exit 7
            }
            $userdata = $manifest.inputs.userdata.path
            if (-not $userdata) { Write-Error 'Manifest has no userdata image.'; exit 8 }
            $userdataPath = Join-Path $root $userdata
            if (-not (Test-Path -LiteralPath $userdataPath -PathType Leaf)) {
                Write-Error "Missing userdata image: $userdataPath"; exit 9
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
            if (-not $firmwarePath) { Write-Error 'Manifest has no boot firmware image.'; exit 10 }
            $darwinPath = $null
            if ($manifest.inputs.darwin_root.path) {
                $candidate = Join-Path $root $manifest.inputs.darwin_root.path
                if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                    $darwinPath = $candidate
                }
            }
            if ($manifest.inputs.darwin_root.present -and -not $darwinPath) {
                Write-Error 'Manifest declares a darwin root image but it is missing.'; exit 11
            }
            # The darwin root image needs a GPT partition that stock Polaris does
            # not ship. Probe for it instead of letting fastboot flash fail with an
            # opaque 'partition not found' after the checksum pass.
            if ($darwinPath) {
                $probe = (& fastboot.exe getvar partition-size:darwin 2>&1 | Out-String)
                if ($probe -notmatch 'partition-size:\s*darwin:\s*0x[0-9a-fA-F]+') {
                    Write-Error ("The darwin root image cannot be installed: this device has no 'darwin' partition. " +
                        "Stock Polaris exposes 85 partitions and none of them is named darwin. " +
                        "Re-partition the phone first (see research/polaris-partition-plan.md) or rebuild the package without --darwin-root.")
                    exit 12
                }
            }
            if ($darwinPath) {
                Write-Host 'Flashing the qualified darwin root image...'
                & fastboot.exe flash darwin $darwinPath
                if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            }
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
                  darwin_root: Path | None = None,
                  device_validation: Path | None = None,
                  driver_bundle: Path | None = None) -> dict[str, Any]:
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
    darwin_root = darwin_root.resolve() if darwin_root else None
    # Polaris keeps the boot FAT in userdata and SHNGROOT in darwin. Reuse
    # the exact ESP image instead of requiring an unrelated userdata root.
    if darwin_root is not None:
        if userdata is not None and (not userdata.is_file() or sha256(userdata) != sha256(esp_image)):
            raise ValueError("split darwin root requires userdata to be the ESP image")
        userdata = esp_image
    device_validation = device_validation.resolve() if device_validation else None
    driver_bundle = driver_bundle.resolve() if driver_bundle else None

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
        blockers.append("no userdata image was supplied")
    if darwin_root is not None and not darwin_root.is_file():
        blockers.append("the supplied darwin root image is missing")
    if darwin_root is not None and darwin_root.is_file():
        # Stock Polaris ships 85 GPT partitions and none is named darwin, so the
        # root image has nowhere to land until the phone is re-partitioned.
        blockers.append(
            "the darwin root image needs a darwin GPT partition, which stock Polaris does not have"
        )
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
                and validation_report.get("userland_booted") is True
            )
        except (OSError, json.JSONDecodeError):
            blockers.append("device validation report is not valid JSON")
    if device_validation and device_validation.is_file() and not validation_ok:
        blockers.append("device validation report does not attest a temporary Polaris boot")
        if validation_report is not None and validation_report.get("userland_booted") is not True:
            blockers.append("device validation report does not attest a userland boot")

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
    firmware_provenance_target: Path | None = None
    if firmware and firmware.is_file():
        firmware_target = output / "firmware" / firmware.name
        firmware_target.parent.mkdir(parents=True)
        shutil.copy2(firmware, firmware_target)
        provenance_path = firmware.with_name("firmware-provenance.json")
        if provenance_path.is_file():
            firmware_provenance_target = output / provenance_path.name
            shutil.copy2(provenance_path, firmware_provenance_target)
    elif firmware and firmware.is_dir():
        firmware_target = output / "firmware"
        copy_tree(firmware, firmware_target)
    userdata_target = output / ("esp.img" if darwin_root is not None else "userdata.img")
    if userdata and userdata.is_file() and userdata_target != output / "esp.img":
        shutil.copy2(userdata, userdata_target)
    if darwin_root and darwin_root.is_file():
        shutil.copy2(darwin_root, output / "darwin-root.img")
    shutil.copy2(ROOT / "research" / "polaris-hardware-contract.json", output / "polaris-hardware-contract.json")
    shutil.copy2(ROOT / "research" / "polaris-driver-matrix.json", output / "polaris-driver-matrix.json")
    woa_evidence = ROOT / "research" / "polaris-woa-evidence.json"
    if woa_evidence.is_file():
        shutil.copy2(woa_evidence, output / "polaris-woa-evidence.json")
    default_driver_bundle = ROOT / "research" / "polaris-driver-bundle.json"
    selected_driver_bundle = driver_bundle if driver_bundle is not None else default_driver_bundle
    if selected_driver_bundle.is_file():
        shutil.copy2(selected_driver_bundle, output / "polaris-driver-bundle.json")
    elif selected_driver_bundle.is_dir():
        copy_tree(selected_driver_bundle, output / "driver-bundle")

    manifest: dict[str, Any] = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "board": "xiaomi,polaris",
        "variant": {"ram_gib": 6, "storage_gib": 128},
        "target": "UniXNU Darwin 23 / iPadOS 17 ABI research",
        "flashable": flashable,
        "safe_to_flash": flashable,
        "hardware_tested": bool(validation_report and
                                 validation_report.get("hardware_tested") is True),
        "temporary_boot_tested": bool(validation_report and
                                       validation_report.get("temporary_boot") is True),
        "userland_tested": bool(validation_report and
                                 validation_report.get("userland_booted") is True),
        "device_access": {"adb": False, "fastboot": False, "partition_writes": False},
        "inputs": {
            "esp": file_fact(output / "esp", package_root=output),
            "esp_image": file_fact(output / "esp.img", package_root=output),
            "kernel": file_fact(output / "kernel.macho", package_root=output),
            "firmware": file_fact(firmware_target, package_root=output) if firmware_target else {"present": False},
            "firmware_provenance": file_fact(firmware_provenance_target, package_root=output)
            if firmware_provenance_target else {"present": False},
            "userdata": file_fact(userdata_target, package_root=output) if userdata and userdata.is_file() else {"present": False},
            "darwin_root": file_fact(output / "darwin-root.img", package_root=output) if darwin_root and darwin_root.is_file() else {"present": False},
        },
        "kernel": kfacts,
        "driver_contract": contract_report,
        "woa_evidence": file_fact(output / "polaris-woa-evidence.json", package_root=output)
        if woa_evidence.is_file() else {"present": False},
        "driver_bundle": (
            file_fact(output / "polaris-driver-bundle.json", package_root=output)
            if selected_driver_bundle.is_file() else
            file_fact(output / "driver-bundle", package_root=output)
            if selected_driver_bundle.is_dir() else {"present": False}
        ),
        "device_validation": validation_report,
        "firmware_provenance": firmware_provenance,
        "blockers": blockers,
        "installer": {
            "generated": True,
            "commands": ([
                *(["fastboot flash darwin <darwin-root>   # requires a darwin GPT partition; stock Polaris has none"] if darwin_root and darwin_root.is_file() else []),
                "fastboot flash userdata <userdata>", "fastboot boot <firmware>"
            ] if flashable else []),
            "guard": "manifest.flashable must be true and exactly one polaris fastboot device must be present",
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    write_guarded_flash_cmd(output / "flash.cmd")
    write_guarded_flash_ps1(output / "flash.ps1")

    (output / "README.txt").write_text(
        "This is a guarded Polaris UniXNU package.\n"
        f"flashable={str(flashable).lower()}\n"
        "Run flash.cmd only after reviewing manifest.json; the current build refuses to flash when any gate is open.\n",
        encoding="utf-8",
    )
    entries: list[str] = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            entries.append(f"{sha256(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS").write_text("\n".join(entries) + "\n", encoding="ascii")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--esp", type=Path, required=True)
    parser.add_argument("--esp-image", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--firmware", type=Path)
    parser.add_argument("--userdata", type=Path)
    parser.add_argument("--darwin-root", type=Path,
                        help="optional iPadOS SHNGROOT image for the darwin partition")
    parser.add_argument("--device-validation", type=Path)
    parser.add_argument("--driver-bundle", type=Path,
                        help="optional local driver bundle manifest or directory")
    args = parser.parse_args()
    manifest = build_package(args.esp, args.esp_image, args.kernel, args.out,
                             firmware=args.firmware, userdata=args.userdata,
                             darwin_root=args.darwin_root,
                             device_validation=args.device_validation,
                             driver_bundle=args.driver_bundle)
    print(f"wrote guarded Polaris package: {args.out.resolve()}")
    print(f"flashable={manifest['flashable']}")
    for blocker in manifest["blockers"]:
        print(f"BLOCKED: {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
