#!/usr/bin/env python3
"""Offline qualification evaluator for Polaris UFS DMA / apps-SMMU evidence.

Status: host-only decision aid. This file reads a *recorded* JSON evidence
record. It never opens a device, maps MMIO, touches UFS or the SMMU, and it
does not modify or weaken the runtime guard in
drivers/ShengUfs/PolarisDmaHandoff.h.

The checks mirror the enforcement conditions in
  drivers/ShengUfs/NativeUfs.cpp        (startBlock / hostBringUp allocation)
  drivers/ShengUfs/PolarisDmaHandoff.h  (width, mode, stream and stability)
and add the DMA-ownership rules required by the low-address pool design in
research/ufs-dma-qualification.md.

Verdicts:
  qualified  every required check for the requested mode passed
  refused    at least one required check failed
  incomplete no failure, but at least one required fact is missing
CLI exit codes: 0 qualified, 1 refused, 2 incomplete or invalid input.
A template record can never be qualified. A qualified verdict is not a boot
authorization and is not a hardware, media or root-mount claim.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA = "polaris.ufs-dma-evidence.v1"
MODES = ("high_dma", "low_pool")

CAP_64AS = 1 << 24
SMMU_CONTROL_CLIENTPD = 1 << 0
SMMU_CONTROL_EXIDENABLE = 1 << 3
SMMU_IDR0_SMS = 1 << 27
SMR_VALID = 0x80000000
S2CR_TYPE_MASK = 3 << 16
S2CR_TYPE_BYPASS = 1 << 16
GUARD_STREAM_IDS = tuple(range(0x100, 0x110))

K_DMA_BYTES = 0x22000
PAGE_BYTES = 0x1000
MAX_POOL_BYTES = 0x200000
FIRMWARE_REQUEST_LIST_BYTES = 0x4000
UFS_REGISTER_BASE = 0x01D84000
UFS_REGISTER_BYTES = 0x2500
SMMU_REGISTER_BASE = 0x15000000
SMMU_REGISTER_BYTES = 0x1000

OWNED_ALLOCATORS = frozenset({
    "IOBufferMemoryDescriptor.inTaskWithOptions/kernel_task/physically-contiguous",
})
POOL_OWNER = "darwinboot-loader"
POOL_ADT_PROPERTY = "darwinboot-dma-pool"

HEX64 = re.compile(r"^[0-9a-f]{64}$")

PASS = "pass"
FAIL = "fail"
MISSING = "missing"
NOT_REQUIRED = "not_required"

REQUIRED_CHECKS = {
    "high_dma": (
        "E1-controller-width",
        "E2-smmu-registers",
        "E3-smmu-mode",
        "E4-smmu-widths",
        "E5-stream-routing",
        "E6-register-stability",
        "E7-firmware-handoff",
        "E8-dma-ownership",
        "E10-claim-discipline",
    ),
    "low_pool": (
        "E2-smmu-registers",
        "E3-smmu-mode",
        "E4-smmu-widths",
        "E5-stream-routing",
        "E6-register-stability",
        "E7-firmware-handoff",
        "E9-dma-pool",
        "E10-claim-discipline",
    ),
}


def _check(check_id, status, reason, detail=None):
    return {"id": check_id, "status": status, "reason": reason, "detail": detail or {}}


def _section(record, name):
    value = record.get(name)
    return value if isinstance(value, dict) else {}


def _uint(value, bits=64):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > (1 << bits) - 1:
        return None
    return value


def _uint_list(values):
    if not isinstance(values, list):
        return None
    result = []
    for value in values:
        number = _uint(value, 32)
        if number is None:
            return None
        result.append(number)
    return result


def physical_address_bits(code):
    """IDR2/IAS/OAS code -> bits, or None for a reserved encoding.

    Deliberately no Linux-style default-to-48 fallback: a reserved code is
    evidence that the snapshot is wrong or the field must be re-read.
    """
    if not isinstance(code, int) or isinstance(code, bool) or code < 0:
        return None
    return {0: 32, 1: 36, 2: 40, 3: 42, 4: 44, 5: 48}.get(code)


def upstream_address_bits(code):
    if not isinstance(code, int) or isinstance(code, bool) or code < 0:
        return None
    if code == 5:
        return 49
    if code == 15:
        return 64
    return physical_address_bits(code)


def range_fits(address, length, bits):
    """Inclusive-last-byte check, mirroring polarisDmaRangeFits()."""
    if _uint(address) is None or _uint(length) is None:
        return False
    if address == 0 or length == 0 or not isinstance(bits, int) or not 0 < bits <= 64:
        return False
    maximum = (1 << 64) - 1 if bits == 64 else (1 << bits) - 1
    return address <= maximum and length - 1 <= maximum - address


def controller_dma_fits(address, length, cap):
    if _uint(cap, 32) is None:
        return False
    return range_fits(address, length, 64 if cap & CAP_64AS else 32)


def _overlaps(first_base, first_bytes, second_base, second_bytes):
    if None in (first_base, second_base):
        return None
    return first_base < second_base + second_bytes and second_base < first_base + first_bytes


def _dma_range(record, mode):
    if mode == "low_pool":
        pool = _section(record, "pool")
        return _uint(pool.get("base")), _uint(pool.get("bytes"))
    dma = _section(record, "dma")
    return _uint(dma.get("address")), _uint(dma.get("bytes"))


def _check_controller(mode, record):
    check_id = "E1-controller-width"
    controller = _section(record, "controller")
    cap = _uint(controller.get("cap"), 32)
    if mode == "low_pool":
        return _check(check_id, NOT_REQUIRED,
                      "low-pool route does not need CAP[24]; the pool itself must stay inside 32 bits (E9)",
                      {"cap": cap})
    if cap is None:
        return _check(check_id, MISSING,
                      "UFSHCI CAP is not recorded; only a read-only register snapshot can provide it")
    address, length = _dma_range(record, mode)
    if address is None or length is None:
        return _check(check_id, MISSING, "DMA address/length not recorded")
    if not controller_dma_fits(address, length, cap):
        limit = 64 if cap & CAP_64AS else 32
        return _check(check_id, FAIL,
                      "DMA range does not fit the controller CAP address width",
                      {"cap": hex(cap), "64as": bool(cap & CAP_64AS), "limit": limit,
                       "address": hex(address), "bytes": length})
    return _check(check_id, PASS, "DMA range fits the controller CAP width",
                  {"cap": hex(cap), "64as": bool(cap & CAP_64AS)})


def _check_smmu_registers(record):
    check_id = "E2-smmu-registers"
    smmu = _section(record, "smmu")
    required = {name: _uint(smmu.get(name), 32)
                for name in ("control", "idr0", "idr2")}
    missing = [name for name, value in required.items() if value is None]
    if missing:
        return _check(check_id, MISSING,
                      "SMMU register snapshot incomplete: " + ", ".join(missing),
                      {"missing": missing})
    smr = _uint_list(smmu.get("smr"))
    s2cr = _uint_list(smmu.get("s2cr"))
    if smr is None or s2cr is None:
        return _check(check_id, MISSING, "SMR/S2CR snapshot is absent or not a uint32 array")
    if len(smr) != len(s2cr):
        return _check(check_id, FAIL, "SMR and S2CR snapshots differ in length",
                      {"smr": len(smr), "s2cr": len(s2cr)})
    groups = required["idr0"] & 0xFF
    if not 1 <= groups <= 128:
        return _check(check_id, FAIL, "IDR0.NUMSMRG is zero or unsupported",
                      {"numsmrg": groups})
    if len(smr) < groups:
        return _check(check_id, MISSING,
                      "SMR/S2CR snapshot shorter than IDR0.NUMSMRG",
                      {"snapshot": len(smr), "numsmrg": groups})
    return _check(check_id, PASS, "SMMU register snapshot present and shaped like the guard expects",
                  {"numsmrg": groups, "snapshot": len(smr)})


def _check_smmu_mode(record):
    check_id = "E3-smmu-mode"
    smmu = _section(record, "smmu")
    control = _uint(smmu.get("control"), 32)
    idr0 = _uint(smmu.get("idr0"), 32)
    if control is None or idr0 is None:
        return _check(check_id, MISSING, "sCR0/IDR0 not recorded")
    if control & SMMU_CONTROL_CLIENTPD:
        return _check(check_id, FAIL, "sCR0.CLIENTPD is set: the SMMU is globally bypassed",
                      {"control": hex(control)})
    if control & SMMU_CONTROL_EXIDENABLE:
        return _check(check_id, FAIL, "sCR0.EXIDENABLE is set: extended stream IDs are not handled",
                      {"control": hex(control)})
    if not idr0 & SMMU_IDR0_SMS:
        return _check(check_id, FAIL, "IDR0.SMS is clear: the SMMU does not support this handoff mode",
                      {"idr0": hex(idr0)})
    return _check(check_id, PASS, "sCR0/IDR0 match the only accepted handoff mode",
                  {"control": hex(control), "idr0": hex(idr0)})


def _check_smmu_widths(mode, record):
    check_id = "E4-smmu-widths"
    smmu = _section(record, "smmu")
    controller = _section(record, "controller")
    idr2 = _uint(smmu.get("idr2"), 32)
    cap = _uint(controller.get("cap"), 32)
    if idr2 is None:
        return _check(check_id, MISSING, "SMMU IDR2 not recorded")
    if cap is None:
        return _check(check_id, MISSING, "UFSHCI CAP not recorded; the 32-bit cap cannot be applied")
    ias = physical_address_bits(idr2 & 0xF)
    oas = physical_address_bits((idr2 >> 4) & 0xF)
    ubs = upstream_address_bits((idr2 >> 8) & 0xF)
    if ias is None or oas is None or ubs is None:
        return _check(check_id, FAIL,
                      "IDR2 contains a reserved IAS/OAS/UBS encoding",
                      {"idr2": hex(idr2), "ias": ias, "oas": oas, "ubs": ubs})
    limit = min(ubs, oas)
    if not cap & CAP_64AS and limit > 32:
        limit = 32
    address, length = _dma_range(record, mode)
    if address is None or length is None:
        return _check(check_id, MISSING,
                      "DMA range not recorded for this mode",
                      {"ias": ias, "oas": oas, "ubs": ubs, "limit": limit})
    detail = {"idr2": hex(idr2), "ias": ias, "oas": oas, "ubs": ubs, "limit": limit,
              "address": hex(address), "bytes": length}
    if not range_fits(address, length, limit):
        return _check(check_id, FAIL,
                      "DMA range exceeds the SMMU UBS/OAS limit (or the 32-bit cap)", detail)
    return _check(check_id, PASS, "DMA range fits the SMMU upstream/output width", detail)


def _check_streams(record):
    check_id = "E5-stream-routing"
    smmu = _section(record, "smmu")
    streams = _section(record, "streams")
    smr = _uint_list(smmu.get("smr"))
    s2cr = _uint_list(smmu.get("s2cr"))
    ids = _uint_list(streams.get("ufs_stream_ids"))
    source = streams.get("source")
    if smr is None or s2cr is None or len(smr) != len(s2cr):
        return _check(check_id, MISSING, "SMR/S2CR snapshot absent or inconsistent")
    if not ids:
        return _check(check_id, MISSING, "UFS stream IDs are not recorded")
    if tuple(sorted(ids)) != GUARD_STREAM_IDS:
        return _check(check_id, FAIL,
                      "recorded stream IDs are not the set the current guard enforces (0x100..0x10f); "
                      "the guard must not be broadened or guessed from an unverified source",
                      {"recorded": [hex(value) for value in ids]})
    if not isinstance(source, str) or not source.strip():
        return _check(check_id, MISSING, "stream ID source is not recorded")
    idr0 = _uint(smmu.get("idr0"), 32)
    if idr0 is None:
        return _check(check_id, MISSING, "IDR0 not recorded; the mapping-group count is unknown")
    groups = idr0 & 0xFF
    if not 1 <= groups <= 128:
        return _check(check_id, FAIL, "IDR0.NUMSMRG is zero or unsupported", {"numsmrg": groups})
    for sid in GUARD_STREAM_IDS:
        matches = 0
        for index in range(groups):
            entry = smr[index]
            if not entry & SMR_VALID:
                continue
            mask = (entry >> 16) & 0x7FFF
            if ((entry ^ sid) & 0x7FFF & ~mask) != 0:
                continue
            matches += 1
            if matches > 1:
                return _check(check_id, FAIL,
                              "overlapping SMR mappings for UFS stream ID",
                              {"sid": hex(sid), "slots": [hex(entry) for entry in smr[:groups]]})
            if (s2cr[index] >> 16) & 3 != 1:
                return _check(check_id, FAIL,
                              "UFS stream is not explicit BYPASS; translated/FAULT routing is not identity",
                              {"sid": hex(sid), "s2cr": hex(s2cr[index])})
        if matches != 1:
            return _check(check_id, FAIL, "UFS stream has no proven SMR mapping",
                          {"sid": hex(sid), "matches": matches})
    detail = {"sids": len(GUARD_STREAM_IDS), "source": source}
    if isinstance(streams.get("mask"), int) and isinstance(streams.get("base"), int):
        detail["base"] = hex(streams["base"])
        detail["mask"] = hex(streams["mask"])
    return _check(check_id, PASS, "every guarded UFS stream has exactly one explicit BYPASS mapping", detail)


def _check_stability(record):
    check_id = "E6-register-stability"
    value = record.get("registers_stable")
    if value is None:
        return _check(check_id, MISSING, "register re-read stability not recorded")
    if value is not True:
        return _check(check_id, FAIL, "SMMU/controller registers changed during the snapshot; "
                                      "the handoff state is not stable and must not be trusted")
    return _check(check_id, PASS, "snapshot registers were stable on re-read")


def _check_firmware_handoff(record):
    check_id = "E7-firmware-handoff"
    handoff = _section(record, "firmware_handoff")
    powered = handoff.get("powered")
    clocks = handoff.get("clocks")
    idle = handoff.get("controller_idle")
    used_after = handoff.get("ufs_used_by_firmware_after_handoff")
    source = handoff.get("source")
    artifact = handoff.get("artifact_sha256")
    missing = []
    for name, value in (("powered", powered), ("clocks", clocks), ("controller_idle", idle),
                        ("ufs_used_by_firmware_after_handoff", used_after)):
        if value is None:
            missing.append(name)
    if missing:
        return _check(check_id, MISSING, "firmware/handoff facts missing: " + ", ".join(missing))
    failures = []
    if powered is not True or clocks is not True or idle is not True:
        failures.append("UFS is not proven powered, clocked and idle at handoff")
    if used_after is not False:
        failures.append("firmware must not keep using UFS MMIO/DMA after handoff")
    if not isinstance(source, str) or not source.strip():
        failures.append("firmware source is not pinned")
    if not isinstance(artifact, str) or not HEX64.match(artifact):
        failures.append("firmware artifact SHA-256 is not recorded")
    if failures:
        return _check(check_id, FAIL, "; ".join(failures),
                      {"source": source, "artifact_sha256": artifact})
    return _check(check_id, PASS, "firmware handoff evidence is pinned and internally consistent",
                  {"source": source, "artifact_sha256": artifact})


def _check_dma_ownership(record):
    check_id = "E8-dma-ownership"
    dma = _section(record, "dma")
    address = _uint(dma.get("address"))
    length = _uint(dma.get("bytes"))
    allocator = dma.get("allocator")
    contiguous = dma.get("physically_contiguous")
    if address is None or length is None or not isinstance(allocator, str):
        return _check(check_id, MISSING, "DMA allocation record incomplete")
    failures = []
    if address == 0 or address % PAGE_BYTES:
        failures.append("DMA address is zero or not page aligned")
    if length < K_DMA_BYTES:
        failures.append("DMA allocation is smaller than kDmaBytes")
    if contiguous is not True:
        failures.append("DMA allocation is not proven physically contiguous")
    if allocator not in OWNED_ALLOCATORS:
        failures.append("DMA buffer is not from the owned kernel-task allocation path")
    firmware_list = _uint(dma.get("firmware_request_list"))
    if firmware_list is None:
        return _check(check_id, MISSING, "firmware request-list base is not recorded",
                      {"failures": failures})
    if _overlaps(address, length, firmware_list, FIRMWARE_REQUEST_LIST_BYTES):
        failures.append("DMA buffer overlaps the firmware request list (not owned memory)")
    detail = {"address": hex(address), "bytes": length, "allocator": allocator,
              "firmware_request_list": hex(firmware_list)}
    if failures:
        return _check(check_id, FAIL, "; ".join(failures), detail)
    return _check(check_id, PASS, "DMA buffer is owned, contiguous and disjoint from firmware pages", detail)


def _check_low_pool(record):
    check_id = "E9-dma-pool"
    pool = _section(record, "pool")
    dma = _section(record, "dma")
    base = _uint(pool.get("base"))
    length = _uint(pool.get("bytes"))
    firm = {
        "owner": pool.get("owner"),
        "adt_property": pool.get("adt_property"),
        "loader_allocated": pool.get("loader_allocated"),
        "uefi_memory_map_verified": pool.get("uefi_memory_map_verified"),
        "borrowed_firmware_pages": pool.get("borrowed_firmware_pages"),
        "provenance_sha256": pool.get("provenance_sha256"),
    }
    missing = [name for name, value in firm.items() if value is None]
    if base is None or length is None or missing:
        return _check(check_id, MISSING,
                      "pool record incomplete: " + ", ".join(
                          ([] if base is not None else ["base"])
                          + ([] if length is not None else ["bytes"])
                          + missing))
    failures = []
    if base == 0 or base % PAGE_BYTES:
        failures.append("pool base is zero or not page aligned")
    if length % PAGE_BYTES:
        failures.append("pool size is not page aligned")
    if length < K_DMA_BYTES:
        failures.append("pool is smaller than kDmaBytes")
    if length > MAX_POOL_BYTES:
        failures.append("pool is larger than the accepted single-slot size")
    if not range_fits(base, length, 32):
        failures.append("pool does not fit below 2^32")
    if firm["owner"] != POOL_OWNER:
        failures.append("pool owner is not the boot-chain loader")
    if firm["adt_property"] != POOL_ADT_PROPERTY:
        failures.append("pool is not declared through the documented ADT property")
    if firm["loader_allocated"] is not True:
        failures.append("pool was not allocated by the loader from UEFI conventional memory")
    if firm["uefi_memory_map_verified"] is not True:
        failures.append("UEFI memory-map intersection was not verified at allocation time")
    if firm["borrowed_firmware_pages"] is not False:
        failures.append("pool is not proven free of borrowed firmware pages")
    if not isinstance(firm["provenance_sha256"], str) or not HEX64.match(firm["provenance_sha256"]):
        failures.append("pool provenance (memory-map snapshot) SHA-256 is not recorded")
    firmware_list = _uint(dma.get("firmware_request_list"))
    if firmware_list is None:
        return _check(check_id, MISSING, "firmware request-list base is not recorded",
                      {"failures": failures})
    if _overlaps(base, length, firmware_list, FIRMWARE_REQUEST_LIST_BYTES):
        failures.append("pool overlaps the firmware request list")
    if _overlaps(base, length, UFS_REGISTER_BASE, UFS_REGISTER_BYTES):
        failures.append("pool overlaps the UFS MMIO window")
    if _overlaps(base, length, SMMU_REGISTER_BASE, SMMU_REGISTER_BYTES):
        failures.append("pool overlaps the SMMU MMIO window")
    detail = {"base": hex(base), "bytes": length, "owner": firm["owner"],
              "adt_property": firm["adt_property"]}
    if failures:
        return _check(check_id, FAIL, "; ".join(failures), detail)
    return _check(check_id, PASS, "owned low-address pool satisfies the documented contract", detail)


def _check_claim_discipline(record):
    check_id = "E10-claim-discipline"
    observations = _section(record, "observations")
    ready = observations.get("media_ready")
    if ready is None or ready is False:
        return _check(check_id, PASS, "no media/root readiness is claimed")
    if ready is not True:
        return _check(check_id, FAIL, "media_ready must be a boolean")
    failures = []
    if observations.get("observer") != "IOMedia":
        failures.append("media readiness must come from an observed IOMedia service")
    if observations.get("whole") is not True:
        failures.append("observed media is not a whole-window media")
    if observations.get("writable") is not False:
        failures.append("observed media is not read-only")
    if _uint(observations.get("size_bytes")) in (None, 0):
        failures.append("observed media size is not recorded")
    if observations.get("ancestry_verified") is not True:
        failures.append("IOMedia ancestry to the exact window device is not verified")
    if failures:
        return _check(check_id, FAIL, "; ".join(failures))
    return _check(check_id, PASS, "media readiness, if claimed, would be backed by an IOMedia observation")


def evaluate(record):
    """Evaluate one evidence record and return a JSON-serializable decision."""
    if not isinstance(record, dict):
        raise ValueError("evidence record must be a JSON object")
    mode = record.get("mode")
    checks = []
    if mode not in MODES:
        checks.append(_check("E0-mode", FAIL,
                             "record mode must be one of: " + ", ".join(MODES)))
        return _result(mode, checks)
    checks.append(_check_controller(mode, record))
    checks.append(_check_smmu_registers(record))
    checks.append(_check_smmu_mode(record))
    checks.append(_check_smmu_widths(mode, record))
    checks.append(_check_streams(record))
    checks.append(_check_stability(record))
    checks.append(_check_firmware_handoff(record))
    checks.append(_check_low_pool(record) if mode == "low_pool" else _check_dma_ownership(record))
    checks.append(_check_claim_discipline(record))
    return _result(mode, checks)


def _result(mode, checks):
    required = REQUIRED_CHECKS.get(mode, ())
    by_id = {check["id"]: check for check in checks}
    failures = [check_id for check_id in required
                if by_id.get(check_id, {}).get("status") == FAIL]
    missed = [check_id for check_id in required
              if check_id not in by_id or by_id[check_id].get("status") == MISSING]
    if not required:
        # An unreadable/unsupported record is refused, never merely incomplete.
        verdict = "refused" if any(check["status"] == FAIL for check in checks) else "incomplete"
    elif failures:
        verdict = "refused"
    elif missed:
        verdict = "incomplete"
    else:
        verdict = "qualified"
    counts = {PASS: 0, FAIL: 0, MISSING: 0, NOT_REQUIRED: 0}
    for check in checks:
        counts[check["status"]] = counts.get(check["status"], 0) + 1
    return {
        "schema": SCHEMA,
        "mode": mode if mode in MODES else None,
        "verdict": verdict,
        "required": list(required),
        "failed_required": failures,
        "missing_required": missed,
        "summary": {"pass": counts[PASS], "fail": counts[FAIL],
                    "missing": counts[MISSING], "not_required": counts[NOT_REQUIRED]},
        "checks": checks,
        "notes": [
            "host-only evidence evaluator; enforcement stays in PolarisDmaHandoff.h",
            "qualified is not a boot authorization and not a hardware/root claim",
            "the record's own status field is informational and is ignored by this evaluator",
        ],
    }


def render_text(result, record_path=None):
    lines = []
    if record_path is not None:
        lines.append("record: " + str(record_path))
    lines.append("mode: " + str(result["mode"]))
    lines.append("verdict: " + result["verdict"].upper())
    lines.append("required: %d" % len(result["required"]))
    for check in result["checks"]:
        lines.append("[%s] %s: %s" % (check["status"].upper(), check["id"], check["reason"]))
    for note in result["notes"]:
        lines.append("note: " + note)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path, help="JSON evidence record")
    parser.add_argument("--json", action="store_true", help="print the full decision as JSON")
    args = parser.parse_args(argv)
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
        result = evaluate(record)
    except (OSError, ValueError) as error:
        print("invalid evidence record: %s" % error, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_text(result, args.record))
    if result["verdict"] == "qualified":
        return 0
    if result["verdict"] == "refused":
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
