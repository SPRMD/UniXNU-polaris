import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "polaris_dma_qualification", HERE / "polaris_dma_qualification.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
TEMPLATE = HERE / "ufs-dma-evidence-template.json"

OWNED = "IOBufferMemoryDescriptor.inTaskWithOptions/kernel_task/physically-contiguous"


def high_dma_record():
    return {
        "schema": MODULE.SCHEMA,
        "mode": "high_dma",
        "status": "unqualified",
        "controller": {"cap": 0x01000000, "version": 0x00000300},
        "smmu": {
            "control": 0,
            "idr0": (1 << 27) | 16,
            "idr1": 0x00000052,
            "idr2": (5 << 0) | (5 << 4) | (15 << 8),
            "smr": [0x800F0100] + [0] * 15,
            "s2cr": [(1 << 16)] * 16,
        },
        "streams": {
            "ufs_stream_ids": list(range(0x100, 0x110)),
            "source": "mainline sdm845.dtsi: iommus = <&apps_smmu 0x100 0xf>",
            "base": 0x100,
            "mask": 0xF,
        },
        "dma": {
            "address": 0x100020000,
            "bytes": MODULE.K_DMA_BYTES,
            "allocator": OWNED,
            "physically_contiguous": True,
            "firmware_request_list": 0xC8000000,
        },
        "firmware_handoff": {
            "powered": True,
            "clocks": True,
            "controller_idle": True,
            "ufs_used_by_firmware_after_handoff": False,
            "source": "edk2-msm fork build run 40061045714",
            "artifact_sha256": "a" * 64,
        },
        "registers_stable": True,
        "observations": {"media_ready": False},
    }


def low_pool_record():
    record = high_dma_record()
    record["mode"] = "low_pool"
    record["controller"] = {"cap": 0x00000000, "version": 0x00000300}
    record["dma"] = {"firmware_request_list": 0xC8000000}
    record["pool"] = {
        "base": 0x9A000000,
        "bytes": 0x40000,
        "owner": "darwinboot-loader",
        "adt_property": "darwinboot-dma-pool",
        "loader_allocated": True,
        "uefi_memory_map_verified": True,
        "borrowed_firmware_pages": False,
        "provenance_sha256": "b" * 64,
    }
    return record


class QualificationEvaluatorTests(unittest.TestCase):
    def evaluate(self, record):
        return MODULE.evaluate(copy.deepcopy(record))

    def statuses(self, result):
        return {check["id"]: check["status"] for check in result["checks"]}

    # -- accepted shapes ---------------------------------------------------
    def test_high_dma_route_qualifies_with_full_evidence(self):
        result = self.evaluate(high_dma_record())
        self.assertEqual(result["verdict"], "qualified")
        self.assertEqual(result["failed_required"], [])
        status = self.statuses(result)
        for check_id in MODULE.REQUIRED_CHECKS["high_dma"]:
            self.assertEqual(status[check_id], "pass", check_id)

    def test_low_pool_route_qualifies_without_64as_controller(self):
        result = self.evaluate(low_pool_record())
        self.assertEqual(result["verdict"], "qualified")
        status = self.statuses(result)
        self.assertEqual(status["E1-controller-width"], "not_required")
        self.assertEqual(status["E9-dma-pool"], "pass")

    def test_template_is_incomplete_and_never_qualified(self):
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        result = MODULE.evaluate(template)
        self.assertEqual(result["verdict"], "incomplete")
        status = {check["id"]: check["status"] for check in result["checks"]}
        self.assertEqual(status["E9-dma-pool"], "missing")
        self.assertFalse(any(check["status"] == "fail" for check in result["checks"]))

    # -- controller / SMMU width axis --------------------------------------
    def test_above_4gib_requires_cap_64as(self):
        record = high_dma_record()
        record["controller"]["cap"] = 0
        result = self.evaluate(record)
        self.assertEqual(result["verdict"], "refused")
        self.assertIn("E1-controller-width", result["failed_required"])

    def test_reserved_idr2_width_encoding_is_refused(self):
        record = high_dma_record()
        record["smmu"]["idr2"] = (6 << 0) | (5 << 4) | (15 << 8)
        result = self.evaluate(record)
        self.assertEqual(result["verdict"], "refused")
        self.assertIn("E4-smmu-widths", result["failed_required"])

    def test_ubs_49_and_64_encodings_are_accepted(self):
        for code, width in ((5, 49), (15, 64)):
            record = high_dma_record()
            record["smmu"]["idr2"] = (5 << 0) | (5 << 4) | (code << 8)
            result = self.evaluate(record)
            self.assertEqual(result["verdict"], "qualified", code)
            detail = next(check for check in result["checks"]
                          if check["id"] == "E4-smmu-widths")["detail"]
            self.assertEqual(detail["ubs"], width)

    def test_smmu_mode_clientpd_and_sms_are_refused(self):
        for section, value, check_id in (
            ("control", 1, "E3-smmu-mode"),
            ("idr0", 16, "E3-smmu-mode"),
        ):
            record = high_dma_record()
            record["smmu"][section] = value
            result = self.evaluate(record)
            self.assertEqual(result["verdict"], "refused", section)
            self.assertIn(check_id, result["failed_required"])

    def test_idr0_numsmrg_bounds_are_enforced(self):
        for value in (0, 129):
            record = high_dma_record()
            record["smmu"]["idr0"] = (1 << 27) | value
            result = self.evaluate(record)
            self.assertEqual(result["verdict"], "refused", value)
            self.assertIn("E2-smmu-registers", result["failed_required"])

    # -- stream routing ----------------------------------------------------
    def test_translated_stream_is_not_identity(self):
        record = high_dma_record()
        record["smmu"]["s2cr"][0] = 0
        result = self.evaluate(record)
        self.assertEqual(result["verdict"], "refused")
        self.assertIn("E5-stream-routing", result["failed_required"])

    def test_overlapping_smr_is_refused(self):
        record = high_dma_record()
        record["smmu"]["smr"][1] = 0x80000100
        result = self.evaluate(record)
        self.assertEqual(result["verdict"], "refused")
        self.assertIn("E5-stream-routing", result["failed_required"])

    def test_missing_stream_mapping_is_refused(self):
        record = high_dma_record()
        record["smmu"]["smr"] = [0] * 16
        result = self.evaluate(record)
        self.assertEqual(result["verdict"], "refused")
        self.assertIn("E5-stream-routing", result["failed_required"])

    def test_unproven_stream_id_set_is_refused(self):
        record = high_dma_record()
        record["streams"]["ufs_stream_ids"] = [0x720]
        result = self.evaluate(record)
        self.assertEqual(result["verdict"], "refused")
        self.assertIn("E5-stream-routing", result["failed_required"])

    def test_register_stability_is_required(self):
        record = high_dma_record()
        record["registers_stable"] = False
        self.assertEqual(self.evaluate(record)["verdict"], "refused")
        record["registers_stable"] = None
        self.assertEqual(self.evaluate(record)["verdict"], "incomplete")

    # -- firmware handoff --------------------------------------------------
    def test_firmware_artifact_must_be_pinned(self):
        record = high_dma_record()
        record["firmware_handoff"]["artifact_sha256"] = "deadbeef"
        self.assertEqual(self.evaluate(record)["verdict"], "refused")
        record["firmware_handoff"]["source"] = ""
        record["firmware_handoff"]["artifact_sha256"] = "a" * 64
        self.assertEqual(self.evaluate(record)["verdict"], "refused")

    def test_firmware_must_stop_using_ufs(self):
        record = high_dma_record()
        record["firmware_handoff"]["ufs_used_by_firmware_after_handoff"] = True
        self.assertEqual(self.evaluate(record)["verdict"], "refused")

    # -- high-route DMA ownership -----------------------------------------
    def test_dma_must_not_reuse_firmware_request_list(self):
        record = high_dma_record()
        record["dma"]["address"] = 0xC8001000
        result = self.evaluate(record)
        self.assertEqual(result["verdict"], "refused")
        self.assertIn("E8-dma-ownership", result["failed_required"])

    def test_dma_allocator_must_be_owned_kernel_path(self):
        record = high_dma_record()
        record["dma"]["allocator"] = "firmware-request-list-reuse"
        result = self.evaluate(record)
        self.assertEqual(result["verdict"], "refused")
        self.assertIn("E8-dma-ownership", result["failed_required"])

    def test_dma_must_be_physically_contiguous(self):
        record = high_dma_record()
        record["dma"]["physically_contiguous"] = False
        self.assertEqual(self.evaluate(record)["verdict"], "refused")

    # -- low-pool ownership -------------------------------------------------
    def test_pool_must_fit_below_4gib(self):
        record = low_pool_record()
        record["pool"]["base"] = 0x100000000
        result = self.evaluate(record)
        self.assertEqual(result["verdict"], "refused")
        self.assertIn("E9-dma-pool", result["failed_required"])

    def test_pool_wrap_past_4gib_is_refused(self):
        record = low_pool_record()
        record["pool"]["base"] = 0xFFFFE000
        record["pool"]["bytes"] = 0x22000
        result = self.evaluate(record)
        self.assertEqual(result["verdict"], "refused")
        self.assertIn("E9-dma-pool", result["failed_required"])

    def test_pool_must_not_borrow_firmware_pages(self):
        record = low_pool_record()
        record["pool"]["borrowed_firmware_pages"] = True
        self.assertEqual(self.evaluate(record)["verdict"], "refused")

    def test_pool_must_be_verified_against_uefi_memory_map(self):
        record = low_pool_record()
        record["pool"]["uefi_memory_map_verified"] = False
        self.assertEqual(self.evaluate(record)["verdict"], "refused")

    def test_pool_must_be_single_slot_sized_and_aligned(self):
        for base, length in ((0x9A000800, 0x40000), (0x9A000000, 0x1000),
                             (0x9A000000, 0x400000)):
            record = low_pool_record()
            record["pool"]["base"], record["pool"]["bytes"] = base, length
            self.assertEqual(self.evaluate(record)["verdict"], "refused", (base, length))

    def test_pool_must_not_overlap_ufs_mmio(self):
        record = low_pool_record()
        record["pool"]["base"] = 0x01D84000
        record["pool"]["bytes"] = 0x10000
        self.assertEqual(self.evaluate(record)["verdict"], "refused")

    # -- claim discipline --------------------------------------------------
    def test_media_ready_claim_requires_iomedia_observation(self):
        record = high_dma_record()
        record["observations"] = {"media_ready": True}
        result = self.evaluate(record)
        self.assertEqual(result["verdict"], "refused")
        self.assertIn("E10-claim-discipline", result["failed_required"])

    def test_media_ready_claim_with_observation_is_accepted(self):
        record = high_dma_record()
        record["observations"] = {
            "media_ready": True,
            "observer": "IOMedia",
            "whole": True,
            "writable": False,
            "size_bytes": 0x100000,
            "ancestry_verified": True,
        }
        self.assertEqual(self.evaluate(record)["verdict"], "qualified")

    # -- helper semantics --------------------------------------------------
    def test_range_and_width_helpers(self):
        self.assertTrue(MODULE.range_fits(0xFFFFFFE0, 0x20, 32))
        self.assertFalse(MODULE.range_fits(0xFFFFFFE0, 0x21, 32))
        self.assertFalse(MODULE.range_fits(0x100000000, 1, 32))
        self.assertTrue(MODULE.range_fits(0x100000000, 1, 33))
        self.assertTrue(MODULE.controller_dma_fits(0x100000000, MODULE.K_DMA_BYTES, 1 << 24))
        self.assertFalse(MODULE.controller_dma_fits(0x100000000, MODULE.K_DMA_BYTES, 0))
        self.assertIsNone(MODULE.physical_address_bits(6))
        self.assertEqual(MODULE.physical_address_bits(5), 48)
        self.assertEqual(MODULE.upstream_address_bits(5), 49)
        self.assertEqual(MODULE.upstream_address_bits(15), 64)

    def test_invalid_mode_is_refused(self):
        record = high_dma_record()
        record["mode"] = "just_boot_it"
        result = self.evaluate(record)
        self.assertEqual(result["verdict"], "refused")

    # -- CLI contract ------------------------------------------------------
    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix="polaris-ufs-dma-") as directory:
            root = Path(directory)
            qualified = root / "qualified.json"
            qualified.write_text(json.dumps(high_dma_record()), encoding="utf-8")
            self.assertEqual(MODULE.main([str(qualified)]), 0)
            refused = root / "refused.json"
            bad = high_dma_record()
            bad["controller"]["cap"] = 0
            refused.write_text(json.dumps(bad), encoding="utf-8")
            self.assertEqual(MODULE.main([str(refused)]), 1)
            incomplete = root / "incomplete.json"
            incomplete.write_text(json.dumps({"mode": "low_pool"}), encoding="utf-8")
            self.assertEqual(MODULE.main([str(incomplete)]), 2)
            broken = root / "broken.json"
            broken.write_text("{", encoding="utf-8")
            self.assertEqual(MODULE.main([str(broken)]), 2)


if __name__ == "__main__":
    unittest.main()
