"""The A630 board contract must stay tied to the stock Polaris device tree.

These are host-side checks over recorded constants and sources. They prove the
tree agrees with itself; they say nothing about the GPU working.
"""
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "drivers" / "PolarisA630Probe" / "PolarisA630Board.h"
PROBE = ROOT / "drivers" / "PolarisA630Probe" / "PolarisA630Probe.cpp"
RESOURCES = ROOT / "research" / "polaris-a630-resources.json"
MATRIX = ROOT / "research" / "polaris-driver-matrix.json"
GAP = ROOT / "research" / "a630-port-gap.md"


def define(name):
    text = BOARD.read_text(encoding="utf-8")
    match = re.search(rf"#define\s+{name}\s+(\(?[^\n/]+?)\)?\s*$", text, re.MULTILINE)
    if not match:
        raise AssertionError(f"{name} is not defined")
    return match.group(1).strip()


def value(name, _seen=None):
    """Evaluate a header macro, expanding aliases such as (SPI + 32)."""
    _seen = set() if _seen is None else _seen
    if name in _seen:
        raise AssertionError(f"recursive macro {name}")
    _seen.add(name)
    raw = define(name).strip()
    while raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1].strip()
    raw = re.sub(r"(\d)[UuLl]+\b", r"\1", raw)
    if re.fullmatch(r"[0-9a-fA-FxX]+", raw):
        return int(raw, 0)
    # Expand each identifier, then evaluate the remaining arithmetic.
    def expand(match):
        return str(value(match.group(0), _seen))
    expression = re.sub(r"[A-Za-z_]\w*", expand, raw)
    # The #define capture keeps the outer parentheses unbalanced on purpose,
    # so close whatever it opened before evaluating.
    expression += ")" * (expression.count("(") - expression.count(")"))
    if not re.fullmatch(r"[\d\s+\-*/()]+", expression):
        raise AssertionError(f"{name} does not reduce to arithmetic: {expression!r}")
    return int(eval(expression, {"__builtins__": {}}, {}))


class A630BoardContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = json.loads(RESOURCES.read_text(encoding="utf-8"))

    def test_windows_match_the_recorded_device_tree(self):
        gpu = self.resources["gpu"]
        self.assertEqual(value("POLARIS_A630_GPU_BASE"), int(gpu["base"], 16))
        self.assertEqual(value("POLARIS_A630_GPU_BYTES"), int(gpu["bytes"], 16))
        self.assertEqual(value("POLARIS_A630_GPU_CX_MEM_BASE"), int(gpu["cx_mem_base"], 16))
        self.assertEqual(value("POLARIS_A630_GPU_CX_MEM_BYTES"), int(gpu["cx_mem_bytes"], 16))
        gmu = self.resources["gmu"]
        self.assertEqual(value("POLARIS_A630_GMU_BASE"), int(gmu["base"], 16))
        self.assertEqual(value("POLARIS_A630_GMU_BYTES"), int(gmu["bytes"], 16))
        self.assertEqual(value("POLARIS_A630_GMU_PDC_BASE"), int(gmu["pdc_base"], 16))
        self.assertEqual(value("POLARIS_A630_GMU_PDC_BYTES"), int(gmu["pdc_bytes"], 16))
        smmu = self.resources["smmu"]
        self.assertEqual(value("POLARIS_A630_SMMU_BASE"), int(smmu["base"], 16))
        self.assertEqual(value("POLARIS_A630_SMMU_BYTES"), int(smmu["bytes"], 16))
        gpucc = self.resources["gpucc"]
        self.assertEqual(value("POLARIS_A630_GPUCC_BASE"), int(gpucc["base"], 16))
        self.assertEqual(value("POLARIS_A630_GPUCC_BYTES"), int(gpucc["bytes"], 16))

    def test_supporting_windows_match_the_recorded_device_tree(self):
        windows = self.resources["supporting_windows"]
        self.assertEqual(value("POLARIS_A630_GCC_BASE"), int(windows["gcc"]["base"], 16))
        self.assertEqual(value("POLARIS_A630_GCC_BYTES"), int(windows["gcc"]["bytes"], 16))
        self.assertEqual(value("POLARIS_A630_PDC_BASE"), int(windows["pdc"]["base"], 16))
        self.assertEqual(value("POLARIS_A630_PDC_BYTES"), int(windows["pdc"]["bytes"], 16))
        self.assertEqual(value("POLARIS_A630_RSCC_BASE"), int(windows["rscc"]["base"], 16))
        self.assertEqual(value("POLARIS_A630_RSCC_BYTES"), int(windows["rscc"]["bytes"], 16))

    def test_interrupts_are_spi_plus_32(self):
        gpu = self.resources["gpu"]
        self.assertEqual(value("POLARIS_A630_GPU_IRQ_SPI"), gpu["irq_spi"])
        self.assertEqual(value("POLARIS_A630_GPU_IRQ_INTID"), gpu["irq_intid"])
        self.assertEqual(gpu["irq_intid"], gpu["irq_spi"] + 32)
        gmu = self.resources["gmu"]
        self.assertEqual(value("POLARIS_A630_GMU_HFI_IRQ_SPI"), gmu["irq_spi"]["hfi"])
        self.assertEqual(value("POLARIS_A630_GMU_HFI_IRQ_INTID"), gmu["irq_intid"]["hfi"])
        self.assertEqual(value("POLARIS_A630_GMU_IRQ_INTID"), gmu["irq_intid"]["gmu"])
        for name in ("hfi", "gmu"):
            self.assertEqual(gmu["irq_intid"][name], gmu["irq_spi"][name] + 32)
        smmu = self.resources["smmu"]
        self.assertEqual(value("POLARIS_A630_SMMU_GLOBAL_IRQ0_SPI"), smmu["global_irq_spi"][0])
        self.assertEqual(value("POLARIS_A630_SMMU_GLOBAL_IRQ1_SPI"), smmu["global_irq_spi"][1])
        self.assertEqual(value("POLARIS_A630_SMMU_CONTEXT_IRQ_FIRST_SPI"),
                         smmu["context_irq_spi"][0])
        self.assertEqual(value("POLARIS_A630_SMMU_CONTEXT_IRQ_COUNT"),
                         smmu["context_irq_count"])

    def test_chip_id_is_the_one_the_device_tree_declares(self):
        gpu = self.resources["gpu"]
        self.assertEqual(value("POLARIS_A630_CHIP_ID_DT_DECLARED"), int(gpu["chip_id"], 16))
        # The retired candidate list must not be resurrected as a claim.
        self.assertNotIn("chip-id-candidates", PROBE.read_text(encoding="utf-8"))

    def test_stream_ids_match_the_iommus_tuples(self):
        banks = {b["node"]: b["sid"] for b in self.resources["smmu"]["context_banks"]}
        self.assertEqual(banks["gfx3d_user"], value("POLARIS_A630_GPU_SID"))
        secure = banks["gfx3d_secure"]
        self.assertEqual(sorted(secure),
                         sorted([value("POLARIS_A630_GPU_SECURE_SID_A"),
                                 value("POLARIS_A630_GPU_SECURE_SID_B")]))
        self.assertEqual(value("POLARIS_A630_GPU_SID_COUNT"), 1 + len(secure))

    def test_firmware_regions_match_the_recorded_device_tree(self):
        regions = self.resources["firmware_regions"]
        self.assertEqual(value("POLARIS_A630_GPU_REGION_BASE"), int(regions["gpu_region"]["base"], 16))
        self.assertEqual(value("POLARIS_A630_GPU_REGION_BYTES"), int(regions["gpu_region"]["bytes"], 16))
        self.assertEqual(value("POLARIS_A630_PIL_SPSS_BASE"), int(regions["pil_spss_region"]["base"], 16))
        self.assertEqual(value("POLARIS_A630_PIL_SPSS_BYTES"), int(regions["pil_spss_region"]["bytes"], 16))

    def test_windows_are_ordered_as_the_device_tree_declares(self):
        def span(base, bytes_name):
            return value(base), value(base) + value(bytes_name)
        gpu_lo, gpu_hi = span("POLARIS_A630_GPU_BASE", "POLARIS_A630_GPU_BYTES")
        gmu_lo, gmu_hi = span("POLARIS_A630_GMU_BASE", "POLARIS_A630_GMU_BYTES")
        smmu_lo, smmu_hi = span("POLARIS_A630_SMMU_BASE", "POLARIS_A630_SMMU_BYTES")
        gpucc_lo, gpucc_hi = span("POLARIS_A630_GPUCC_BASE", "POLARIS_A630_GPUCC_BYTES")
        # The stock DT packs the GPU SMMU flush against the end of the kgsl
        # window, and nests the GPUCC block inside kgsl_gmu_reg. Both are real
        # properties of the firmware's own map: a backend must map each window
        # on its own terms instead of assuming the blocks are disjoint.
        self.assertEqual(smmu_lo, gpu_hi)
        self.assertLessEqual(gpu_hi, gmu_lo)
        self.assertGreaterEqual(gpucc_lo, gmu_lo)
        self.assertLessEqual(gpucc_hi, gmu_hi)

    def test_gpucc_is_recorded_as_nested_inside_the_gmu_window(self):
        gmu_lo = value("POLARIS_A630_GMU_BASE")
        gmu_hi = gmu_lo + value("POLARIS_A630_GMU_BYTES")
        gpucc_lo = value("POLARIS_A630_GPUCC_BASE")
        gpucc_hi = gpucc_lo + value("POLARIS_A630_GPUCC_BYTES")
        self.assertTrue(gmu_lo <= gpucc_lo and gpucc_hi <= gmu_hi)
        # And that nesting is exactly what the recorded DT says.
        self.assertEqual(int(self.resources["gpucc"]["base"], 16), gpucc_lo)

    def test_the_contract_still_authorises_nothing(self):
        runtime = self.resources["runtime"]
        for key in ("mmio_allowed", "firmware_load_allowed", "dma_allowed",
                    "smmu_programming_allowed", "darwin_driver_ready", "hardware_tested"):
            self.assertFalse(runtime[key], f"{key} must stay false")
        source = PROBE.read_text(encoding="utf-8")
        for guard in ("polaris-a630-gpu-mmio-performed", "polaris-a630-gmu-started",
                      "polaris-a630-smmu-programmed", "polaris-a630-dma-created",
                      "polaris-a630-darwin-driver-ready"):
            self.assertIn(guard, source)

    def test_driver_matrix_does_not_claim_gpu_readiness(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        gpu = matrix["drivers"]["gpu_adreno630"]
        self.assertFalse(gpu["enabled_by_default"])
        self.assertFalse(gpu["userland_ready"])

    def test_supporting_windows_come_from_their_own_dt_nodes(self):
        source = PROBE.read_text(encoding="utf-8")
        for node in ('"/soc/qcom,gcc@100000"', '"/soc/interrupt-controller@0xb220000"',
                     '"/soc/qcom,sde_rscc@af20000"'):
            self.assertIn(node, source)
        windows = self.resources["supporting_windows"]
        self.assertEqual(int(windows["gcc"]["base"], 16), value("POLARIS_A630_GCC_BASE"))
        self.assertEqual(int(windows["pdc"]["base"], 16), value("POLARIS_A630_PDC_BASE"))
        self.assertEqual(int(windows["rscc"]["base"], 16), value("POLARIS_A630_RSCC_BASE"))

    def test_record_completeness_is_not_readiness(self):
        source = PROBE.read_text(encoding="utf-8")
        # A complete resource record must not imply a usable GPU.
        self.assertIn("polaris-a630-resource-record-complete", source)
        self.assertIn('setProperty("polaris-a630-darwin-driver-ready", false)', source)
        runtime = self.resources["runtime"]
        self.assertFalse(runtime["darwin_driver_ready"])

    def test_iommus_are_not_parsed_as_ranges(self):
        # A {phandle, sid} tuple read as {address, size} would turn SID 0 into a
        # zero-size range and silently drop it; the probe needs its own reader.
        source = PROBE.read_text(encoding="utf-8")
        self.assertIn("readStreamIds", source)
        self.assertIn("readStreamIds(user, userSids, 2)", source)
        self.assertIn("readStreamIds(secure, secureSids, 2)", source)
        self.assertIn("be32(bytes + offset + 4)", source)


class A630RecordedTreeTests(unittest.TestCase):
    """Facts read out of the appended-DTB tail, pinned so they cannot drift.

    Each value here was extracted from the stock Polaris DTB. The point of the
    class is not that they are true of the silicon - it is that the JSON and the
    header keep saying the same thing, and that the awkward ones stay awkward.
    """

    @classmethod
    def setUpClass(cls):
        cls.resources = json.loads(RESOURCES.read_text(encoding="utf-8"))

    def test_highest_bank_bit_is_the_device_tree_value(self):
        # 15 is what qcom,highest-bank-bit declares. A wrong bank bit corrupts
        # every tiled surface silently, so it is worth a dedicated assertion.
        self.assertEqual(self.resources["gpu"]["highest_bank_bit"], 15)
        self.assertIn("highest-bank-bit", self.resources["gpu"]["highest_bank_bit_source"])

    def test_gpu_power_levels_descend_and_match_initial_level(self):
        levels = self.resources["gpu"]["power_levels"]
        self.assertEqual(len(levels), 8)
        self.assertEqual([row["level"] for row in levels], list(range(8)))
        frequencies = [row["gpu_hz"] for row in levels]
        self.assertEqual(frequencies, sorted(frequencies, reverse=True))
        self.assertEqual(frequencies[0], 710000000)
        self.assertEqual(frequencies[-1], 0)
        # initial-pwrlevel indexes this table, so it must be a valid index.
        self.assertLess(self.resources["gpu"]["initial_pwrlevel"], len(levels))
        self.assertEqual(levels[self.resources["gpu"]["initial_pwrlevel"]]["gpu_hz"], 257000000)

    def test_gmu_power_levels_are_the_three_declared_states(self):
        levels = self.resources["gmu"]["power_levels"]
        self.assertEqual([row["gmu_hz"] for row in levels], [0, 200000000, 500000000])

    def test_secure_context_keeps_the_device_tree_order(self):
        # iommus = <&kgsl_smmu 2>, <&kgsl_smmu 1> - 2 before 1. A reader that
        # sorts or deduplicates the tuple would swap which bank is which, so the
        # recorded order is asserted exactly.
        banks = {bank["node"]: bank["sid"] for bank in self.resources["smmu"]["context_banks"]}
        self.assertEqual(banks["gfx3d_user"], 0)
        self.assertEqual(banks["gfx3d_secure"], [2, 1])

    def test_gmu_context_banks_come_from_the_gmu_node(self):
        banks = {bank["node"]: bank["sid"] for bank in self.resources["smmu"]["gmu_context_banks"]}
        self.assertEqual(banks["/soc/qcom,gmu/gmu_user"], 4)
        self.assertEqual(banks["/soc/qcom,gmu/gmu_kernel"], 5)

    def test_lpac_sid_is_not_claimed_from_the_numbering_coincidence(self):
        # The A642L gate wants lpacSid 1; polaris has SID 1 only as the second
        # gfx3d_secure bank. The gap document must say so rather than let a
        # future reader fill the field with 1.
        gap = GAP.read_text(encoding="utf-8")
        self.assertIn("lpacSid", gap)
        self.assertIn("still unresolved", gap)

    def test_quirks_are_recorded_as_booleans_not_values(self):
        quirks = self.resources["gpu"]["quirks"]
        self.assertIn("gpu-quirk-hfi-use-reg", quirks)
        self.assertIn("gpu-quirk-secvid-set-once", quirks)
        self.assertIn("no-nap", quirks)


    def test_gmem_geometry_is_recorded_with_its_provenance(self):
        gpu = self.resources["gpu"]
        self.assertEqual(gpu["gmem_bytes"], 1048576)
        self.assertEqual(gpu["gmem_base"], "0x00100000")
        # The range registers are the UCHE pair 0x0e0b/0x0e0d; a driver that
        # programs one without the other leaves GMEM unreachable.
        regs = gpu["gmem_range_registers"]
        self.assertEqual(regs["min"]["offset"], "0x00000e0b")
        self.assertEqual(regs["max"]["offset"], "0x00000e0d")
        # base + size - 1 must equal what the max register is programmed with.
        base = int(gpu["gmem_base"], 16)
        self.assertEqual(base + gpu["gmem_bytes"] - 1, 0x1FFFFF)
        self.assertIn("hakios.adreno.c", gpu["gmem_source"])

    def test_gmem_disagreement_with_mainline_is_recorded(self):
        # Linux's per-chip A630 entry says 512 KiB, the local Darwin driver
        # programs 1 MiB. The gap document must say so rather than pick one.
        gap = GAP.read_text(encoding="utf-8")
        self.assertIn("512 KiB", gap)
        self.assertIn("1 MiB", gap)
        self.assertIn("discrepancy", gap)

    def test_firmware_inventory_is_hashed_and_claims_no_usability(self):
        inventory = self.resources["firmware_regions"]["a630_firmware_inventory"]
        self.assertTrue(inventory, "the A630 firmware inventory is empty")
        basenames = {row["path"].rsplit("/", 1)[-1] for row in inventory}
        for expected in ("a630_gmu.bin", "a630_sqe.fw", "a630_zap.mdt"):
            self.assertIn(expected, basenames)
        for row in inventory:
            self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$", row["path"])
            self.assertGreater(row["bytes"], 0, row["path"])
            # Owning the bytes is not loading them.
            self.assertFalse(row["usable_for_polaris"], row["path"])
            self.assertIn("reason", row)
            self.assertTrue(row["reason"].strip(), row["path"])

    def test_firmware_copies_of_the_same_name_are_not_assumed_identical(self):
        # Several vendor dumps carry an a630_gmu.bin and they are NOT all the
        # same size (20480 in one, 32768 in the others). Recording one hash for
        # "the" GMU firmware would hide that, so the inventory must keep every
        # copy separately and the sizes must actually differ somewhere.
        inventory = self.resources["firmware_regions"]["a630_firmware_inventory"]
        gmu = [row for row in inventory if row["path"].endswith("a630_gmu.bin")]
        self.assertGreater(len(gmu), 1)
        sizes = {row["bytes"] for row in gmu}
        self.assertGreater(len(sizes), 1, "expected the GMU copies to differ in size")
        # Distinct (path) keys, so no copy overwrites another.
        self.assertEqual(len({row["path"] for row in gmu}), len(gmu))


class A630SmmuPolicyTests(unittest.TestCase):
    """ASID and context-bank selection must be recorded as what it is.

    SMMU-v2 routes a stream to a context bank by bank index; there is no ASID
    field in any routing register. These tests pin that conclusion to the two
    in-tree register layouts and to the reference-side policy, so a later reader
    cannot turn the A642L "three distinct non-zero ASIDs" gate into a
    device-tree fact or invent a number for it.
    """

    TAKEOVER = ROOT / "drivers" / "ShengUfs" / "SmmuTakeover.h"
    BYPASS = ROOT / ".cache" / "reference" / "UniXNU-sheng" / "package" / "SmmuBypass.h"
    GMUCTX = (ROOT.parents[1] / "references" / "unixnu-adreno6xx"
              / "NativeAdrenoGmuContext.cpp")

    @classmethod
    def setUpClass(cls):
        cls.resources = json.loads(RESOURCES.read_text())
        cls.policy = cls.resources["smmu"]["asid_and_context_bank_policy"]

    def test_context_bank_count_and_interrupts_are_recorded(self):
        smmu = self.resources["smmu"]
        policy = self.policy["device_tree_proves"]
        self.assertEqual(smmu["context_irq_count"], value("POLARIS_A630_SMMU_CONTEXT_IRQ_COUNT"))
        self.assertEqual(smmu["context_irq_count"], len(smmu["context_irq_spi"]))
        self.assertEqual(smmu["context_irq_spi"][0], value("POLARIS_A630_SMMU_CONTEXT_IRQ_FIRST_SPI"))
        self.assertEqual(smmu["context_irq_spi"],
                         list(range(smmu["context_irq_spi"][0],
                                    smmu["context_irq_spi"][0] + smmu["context_irq_count"])))
        self.assertEqual(smmu["global_irq_spi"],
                         [value("POLARIS_A630_SMMU_GLOBAL_IRQ0_SPI"),
                          value("POLARIS_A630_SMMU_GLOBAL_IRQ1_SPI")])
        # The recorded copy of the same facts must not drift from the node.
        self.assertEqual(policy["context_irq_count"], smmu["context_irq_count"])
        self.assertEqual(policy["context_irq_spi"], smmu["context_irq_spi"])
        self.assertEqual(policy["global_irq_spi"], smmu["global_irq_spi"])

    def test_device_tree_offers_no_asid_or_bank_index_property(self):
        policy = self.policy
        self.assertFalse(policy["device_tree_proves"]["asid_property_present_on_any_cb_node"])
        self.assertFalse(policy["device_tree_proves"]["bank_index_property_present_on_any_cb_node"])
        # An eight-line fault fan-out is not eight implemented banks: the count
        # is IDR1[7:0] and is only readable live, which the record must say.
        self.assertIn("IDR1", policy["device_tree_proves"]["note"])

    def test_no_routing_register_carries_an_asid_field(self):
        self.assertFalse(self.policy["asid_field_in_hardware"])
        layout = self.policy["register_layout_evidence"]
        # SMR is the SID match, S2CR is the type plus the bank index, CBAR and
        # CBA2R describe the bank. None of them has an ASID field.
        self.assertTrue(layout["smr"].startswith("0x0800 + 4*slot"))
        self.assertTrue(layout["s2cr"].startswith("0x0c00 + 4*slot"))
        self.assertIn("CBNDX bits7:0", layout["s2cr"])
        self.assertTrue(layout["cbar"].startswith("0x1000 + 4*bank"))
        self.assertTrue(layout["cba2r"].startswith("0x1800 + 4*bank"))
        for name, field in layout.items():
            if not isinstance(field, str) or name == "sources":
                continue
            self.assertNotIn("ASID", field.upper())
        # Selection is a chain of bank indices, and it is spelled out.
        self.assertIn("CBNDX", layout["selection_path"])
        self.assertIn("SMR", layout["selection_path"])
        # A third, independent reader of the same layout must agree.
        if self.GMUCTX.is_file():
            gmu = self.GMUCTX.read_text()
            self.assertIn("page+4*bank,&image->cbar", gmu.replace(" ", ""))
            self.assertIn("0x800+4*bank,&image->cba2r", gmu.replace(" ", ""))
            self.assertIn("(pages+bank)*(*page)", gmu.replace(" ", ""))
            self.assertIn("(id1>>28)&7", gmu.replace(" ", ""))

    def test_the_in_tree_layouts_agree_with_the_record(self):
        if not self.TAKEOVER.is_file():
            self.skipTest("UFS SMMU planner not present")
        takeover = self.TAKEOVER.read_text()
        # The shipped planner writes the bank number into S2CR and the stream
        # into SMR, which is the whole of the routing model.
        self.assertIn("write(0xc00 + 4 * p.slot, p.bank)", takeover)
        self.assertIn("read(0xc00 + 4 * p.slot) != p.bank", takeover)
        self.assertIn("write(0x800 + 4 * p.slot, 0x80000000U | stream)", takeover)
        self.assertIn("read(0x1000 + 4 * p.bank) != 0x10000", takeover)
        self.assertIn("read(0x1800 + 4 * p.bank)", takeover)
        # Geometry is read, never assumed.
        self.assertIn("idr0 & 255", takeover)
        self.assertIn("idr1 & 255", takeover)
        self.assertIn("1U << (((idr1 >> 28) & 7) + 1)", takeover)
        # And the planner's bank choice is an index from the top, not an ASID.
        self.assertIn("p.bank = banks - 1 - bankFromTop", takeover)

    def test_the_bypass_peer_reads_the_same_fields(self):
        if not self.BYPASS.is_file():
            self.skipTest("Sheng bypass peer not present")
        bypass = self.BYPASS.read_text()
        self.assertIn("((s2cr >> 16) & 3) == 0", bypass)
        self.assertIn("(s2cr & 255) == p.bank", bypass)
        self.assertIn("unsigned banks = idr1 & 255;", bypass)
        self.assertIn("io->wr(io->ctx, 0x1000 + 4 * p->bank, 0x10000)", bypass)
        self.assertIn("io->wr(io->ctx, 0x1800 + 4 * p->bank, 1)", bypass)

    def test_the_asid_is_a_stage_one_identity_not_a_routing_field(self):
        # Where ASID does appear: the per-bank TLB maintenance call, bounded to
        # the architectural width, and the bank's own invalidation prose.
        self.assertTrue(self.policy["asid_used_by"])
        joined = " ".join(self.policy["asid_used_by"])
        self.assertIn("0xffff", joined)
        self.assertIn("SyncContextTlb", joined)
        self.assertIn("TLBIALL", joined)
        # The TTBR0 field position is not asserted: the kit sources are absent.
        self.assertIn("unknown", self.policy["asid_ttbr0_bit_position"])
        self.assertIn("kits/ArmSmmu4K", self.policy["asid_ttbr0_bit_position"])

    def test_reference_asid_policy_is_not_derivable_here(self):
        reference = self.policy["reference_policy"]
        self.assertFalse(reference["derivable_from_polaris_device_tree"])
        self.assertEqual(reference["lpac_sid"], "unresolved")
        self.assertIn("gfx3d_secure", reference["lpac_sid_note"])
        # Three distinct non-zero ASIDs are a choice the port must make; the DT
        # only fixes which stream IDs exist and how faults are reported.
        self.assertIn("pairwise distinct", reference["gate"])
        self.assertEqual(sorted(self.policy["device_tree_proves"]["stream_ids"]),
                         ["gfx3d_secure", "gfx3d_user", "gmu_kernel", "gmu_user"])

    def test_bank_assignment_stays_a_runtime_question(self):
        runtime = self.policy["bank_assignment_is_runtime"]
        self.assertFalse(runtime["known_offline"])
        for name in ("IDR0", "IDR1", "IDR2"):
            self.assertIn(name, runtime["unknown"])
        self.assertIn("CBA2R", " ".join(runtime["unknown"]))

    def test_the_policy_record_authorises_nothing(self):
        self.assertTrue(self.policy["authorises_nothing"])
        runtime = self.resources["runtime"]
        for key in ("mmio_allowed", "firmware_load_allowed", "dma_allowed",
                    "smmu_programming_allowed", "darwin_driver_ready", "hardware_tested"):
            self.assertFalse(runtime[key], f"{key} must stay false")

    def test_the_gpu_smmu_subtree_names_no_asid_property(self):
        search = self.policy["device_tree_proves"]["property_search"]
        # The strongest form of the answer: the device tree encodes everything
        # else about this SMMU, and has no asid property anywhere near it.
        self.assertEqual(search["properties_with_asid_in_name_in_gpu_subtree"], 0)
        self.assertFalse(search["secure_context_bank_on_any_gpu_cb_node"])
        names = search["gpu_smmu_subtree_property_names"]
        self.assertFalse([n for n in names if "asid" in n.lower()])
        self.assertIn("iommus", names)
        self.assertIn("#global-interrupts", names)
        # Qualcomm marks secure banks elsewhere, so the absence is a choice.
        self.assertTrue(search["secure_context_bank_nodes_in_blob"])
        for node in search["secure_context_bank_nodes_in_blob"]:
            self.assertNotIn("kgsl", node)

    def test_the_interrupt_entries_are_ten_and_decode_to_two_plus_eight(self):
        decoding = self.policy["device_tree_proves"]["interrupt_decoding"]
        entries = decoding["global_entries"] + decoding["context_entries"]
        self.assertEqual(len(entries), 10)
        self.assertEqual(decoding["global_interrupts_property"], len(decoding["global_entries"]))
        self.assertEqual([row[0] for row in decoding["global_entries"]],
                         self.resources["smmu"]["global_irq_spi"])
        self.assertEqual([row[0] for row in decoding["context_entries"]],
                         self.resources["smmu"]["context_irq_spi"])
        # Every entry is a level-high SPI on interrupt controller 0.
        for row in entries:
            self.assertEqual(len(row), 3)
            self.assertEqual(row[1], 4)
            self.assertEqual(row[2], 0)

    def test_gpu_offset_is_recorded_but_not_read_as_a_bank(self):
        unexplained = self.policy["device_tree_proves"]["unexplained_values"]
        self.assertIn("qcom,gpu-offset", unexplained)
        self.assertEqual(unexplained["qcom,gpu-offset"]["value"], "0x48000")
        self.assertIn("not interpreted", unexplained["qcom,gpu-offset"]["reading"])

    def test_gap_document_states_the_negative_result(self):
        gap = GAP.read_text(encoding="utf-8")
        self.assertIn("## ASID and context banks", gap)
        self.assertIn("no ASID field exists", gap)
        self.assertIn("CBNDX", gap)
        self.assertIn("still unresolved", gap)
        # The section must separate proof from assumption explicitly.
        self.assertIn("What the stock DT determines", gap)
        self.assertIn("What the tree proves about the register layout", gap)
        self.assertIn("Verdict on the A642L requirement", gap)


class A630PortGapTests(unittest.TestCase):
    """The reference component must keep refusing Polaris values."""

    REF = ROOT.parents[1] / "references" / "unixnu-adreno6xx" / "NativeAdrenoService.cpp"

    def test_gap_analysis_exists_and_names_the_blocking_fields(self):
        gap = (ROOT / "research" / "a630-port-gap.md").read_text(encoding="utf-8")
        for field in ("chipId", "gmemBytes", "frequencyHz", "gpuSidMask",
                      "gmuSid", "lpacSid"):
            self.assertIn(field, gap)
        # The recorded A642L sentinel must appear as the value Polaris cannot meet.
        self.assertIn("0x06030500", gap)
        self.assertIn("0x06030001", gap)

    def test_reference_still_rejects_a_polaris_chip_id(self):
        if not self.REF.is_file():
            self.skipTest("reference checkout not present")
        source = self.REF.read_text(encoding="utf-8", errors="replace")
        # The component's own gate is what makes the A642L code unusable here.
        self.assertIn("0x06030500", source)
        self.assertIn("kIOReturnBadArgument", source)

    def test_polaris_chip_id_is_not_the_reference_sentinel(self):
        self.assertNotEqual(value("POLARIS_A630_CHIP_ID_DT_DECLARED"), 0x06030500)


class A630FirmwareInventoryTests(unittest.TestCase):
    """The firmware inventory may record artefacts; it may not claim usability."""

    @classmethod
    def setUpClass(cls):
        cls.resources = json.loads(RESOURCES.read_text())
        cls.inventory = cls.resources["firmware_regions"]["a630_firmware_inventory"]

    def test_every_entry_carries_a_real_sha256(self):
        self.assertTrue(self.inventory, "inventory is empty")
        seen = set()
        for entry in self.inventory:
            with self.subTest(path=entry.get("path")):
                self.assertEqual(set(entry) - {"duplicate_of"},
                                 {"path", "bytes", "sha256", "kind",
                                  "usable_for_polaris", "reason"})
                digest = entry["sha256"]
                self.assertRegex(digest, r"^[0-9a-f]{64}$")
                # A placeholder would be all zeros, all one character, or a repeat.
                self.assertNotEqual(digest, "0" * 64)
                self.assertNotEqual(len(set(digest)), 1)
                # Repeated bytes are allowed only when the entry declares which
                # recorded file it duplicates; a silent repeat would be a bug.
                if digest in seen:
                    self.assertIn("duplicate_of", entry,
                                  "identical bytes recorded without duplicate_of")
                    self.assertNotEqual(entry["duplicate_of"], entry["path"])
                seen.add(digest)
                self.assertIsInstance(entry["bytes"], int)
                self.assertGreater(entry["bytes"], 0)

    def test_no_entry_claims_usability(self):
        for entry in self.inventory:
            with self.subTest(path=entry.get("path")):
                self.assertIs(entry["usable_for_polaris"], False)
                self.assertTrue(entry["reason"].strip(),
                                "every entry must say why it is unusable")

    def test_inventory_is_confined_to_a630_names(self):
        # The scan must not drift into other GPU generations or subsystems.
        for entry in self.inventory:
            name = entry["path"].rsplit("/", 1)[-1]
            with self.subTest(path=entry["path"]):
                self.assertRegex(name, r"^a630_(gmu\.bin|sqe\.fw|zap\.(mdt|b\d\d|elf))$")
                self.assertIn(entry["kind"], {
                    "gmu-firmware", "sqe-firmware",
                    "zap-elf-header", "zap-elf-segment", "zap-elf-linked"})

    def test_no_a660_firmware_was_recorded(self):
        # The gap document asserts that no A660 image exists locally. If one
        # ever appears, this inventory and that prose both have to change.
        for entry in self.inventory:
            with self.subTest(path=entry["path"]):
                # a630 is the only Adreno generation allowed here; every other
                # A6xx/A7xx part must be absent, which is the documented claim.
                self.assertNotRegex(entry["path"], r"a6(?:[124-9]\d|xx)|a7\d\d")

    def test_gap_document_states_the_result(self):
        gap = GAP.read_text(encoding="utf-8")
        self.assertIn("a630_firmware_inventory", gap)
        self.assertIn("No A660 firmware image exists", gap)
        self.assertIn("usable_for_polaris: false", gap)
        # The corrected bullet must be anchored in the missing-work list too.
        self.assertIn("A630 firmware loadability", gap)


def fdt_nodes(path):
    """Walk an FDT blob and return [(path, {prop: bytes})] for every node.

    Only the structure tokens that matter are decoded; anything else aborts, so
    a malformed blob fails loudly instead of yielding half a tree.
    """
    import struct

    blob = path.read_bytes()
    (magic, _total, off_struct, off_strings, _off_rsv, _ver, _last, _cpu,
     size_strings, size_struct) = struct.unpack('>10I', blob[:40])
    if magic != 0xD00DFEED:
        raise AssertionError(f"{path.name} is not an FDT blob")
    strings = blob[off_strings:off_strings + size_strings]

    def string_at(offset):
        end = strings.find(b'\0', offset)
        return strings[offset:end].decode('ascii', 'replace')

    nodes = []
    stack = []
    pos = off_struct
    while pos < off_struct + size_struct:
        token = struct.unpack('>I', blob[pos:pos + 4])[0]
        pos += 4
        if token == 1:  # FDT_BEGIN_NODE
            end = blob.find(b'\0', pos)
            name = blob[pos:end].decode('ascii', 'replace')
            pos = (end + 4) & ~3
            stack.append(name)
            nodes.append(('/'.join(part for part in stack if part), {}))
        elif token == 2:  # FDT_END_NODE
            if not stack:
                raise AssertionError('unbalanced FDT_END_NODE')
            stack.pop()
        elif token == 3:  # FDT_PROP
            length, name_off = struct.unpack('>II', blob[pos:pos + 8])
            pos += 8
            value = blob[pos:pos + length]
            pos = (pos + length + 3) & ~3
            nodes[-1][1][string_at(name_off)] = value
        elif token == 4:  # FDT_NOP
            continue
        elif token == 9:  # FDT_END
            break
        else:
            raise AssertionError(f'unexpected FDT token {token}')
    return nodes


def cells(value):
    import struct

    return list(struct.unpack('>%dI' % (len(value) // 4), value))


class A630CommandDatabaseTests(unittest.TestCase):
    """The cmd-db indirection, pinned to what local artefacts actually show.

    The board gives a locator, not a database. These tests hold the document to
    that distinction so a later reader cannot quietly promote the locator to
    "the database address", and so the two disagreeing local DT encodings stay
    recorded side by side.
    """

    LOCATOR = '0xc3f000c'
    MAGIC = '0x0c0330db'
    # The one in-repo DT that uses the reserved-memory encoding.
    POLARIS_DTB = (ROOT / '.cache' / 'reference' / 'edk2-msm-full' / 'Platform'
                   / 'Xiaomi' / 'sdm845' / 'FdtBlob' / 'sdm845-xiaomi-polaris.dtb')

    def gap(self):
        return GAP.read_text(encoding='utf-8')

    def section(self):
        return self.gap().split('## Command database', 1)[1]

    def test_gap_has_a_command_database_section(self):
        self.assertIn('## Command database', self.gap())

    def test_the_locator_is_described_as_a_pointer_not_the_database(self):
        section = self.section()
        # The reg pair must appear verbatim, as cells rather than as a pointer.
        self.assertIn(self.LOCATOR, section)
        self.assertIn('locator', section.lower())
        # And the document must not call 0xc3f000c the database.
        self.assertNotIn('the database at ' + chr(96) + '0xc3f000c' + chr(96), section)

    def test_layout_numbers_come_from_the_in_tree_parser(self):
        section = self.section()
        # 144-byte header, 24-byte entries, magic at +4 - all read from
        # sweet_rpmh.c rather than recalled.
        self.assertIn('144', section)
        self.assertIn('24', section)
        self.assertIn(self.MAGIC, section)
        self.assertIn('sweet_rpmh.c', section)

    def test_arc_indexes_are_not_claimed_to_come_from_an_id_table(self):
        # The reference derives the vote from each resource's auxiliary payload.
        section = self.section()
        self.assertIn('arcVote', section)
        self.assertIn('auxiliary', section)
        # It must say plainly that the premise was wrong, not hedge silently.
        self.assertIn('does not', section.lower())

    def test_both_dt_encodings_are_recorded_and_neither_is_chosen(self):
        section = self.section()
        self.assertIn('0x85fe0000', section)   # reserved-memory form
        self.assertIn(self.LOCATOR, section)   # locator form
        self.assertIn('which', section.lower())  # the open question is named

    def test_the_missing_artefact_is_named(self):
        section = self.section()
        # A reader must be told exactly what would close the gap.
        self.assertIn('0xc3f000c', section)
        self.assertIn('live read', section.lower())

    def test_in_repo_polaris_dtb_uses_the_reserved_memory_encoding(self):
        if not self.POLARIS_DTB.is_file():
            self.skipTest('reference DTB checkout not present')
        nodes = fdt_nodes(self.POLARIS_DTB)
        cmd = [(path, props) for path, props in nodes if 'cmd-db' in path]
        self.assertTrue(cmd, 'no cmd-db node in the reference polaris DTB')
        for _path, props in cmd:
            self.assertEqual(props['compatible'].rstrip(b'\0'), b'qcom,cmd-db')
            # Four cells: two address/size pairs - a reserved region, not a
            # two-cell locator. This is what makes the two forms distinct.
            reg = cells(props['reg'])
            self.assertEqual(len(reg), 4)
            self.assertEqual(reg, [0x0, 0x85FE0000, 0x0, 0x20000])
            # And it must not carry the locator address at all.
            self.assertNotIn(0x0C3F000C, reg)

    def test_no_local_artefact_carries_the_database_magic(self):
        # The document claims a byte scan found nothing. Keep that honest by
        # checking the artefacts the claim is about, not by re-scanning 27k
        # files on every test run.
        magic = bytes.fromhex('db30030c')  # 0x0c0330db little-endian
        for hit in ROOT.rglob('CmdDbDxe.efi'):
            self.assertNotIn(magic, hit.read_bytes(), hit)
        # The DXE driver is a lookup implementation, never the data.
        self.assertIn('CmdDbDxe.efi', self.section())

    def test_command_database_claims_no_readiness(self):
        resources = json.loads(RESOURCES.read_text(encoding='utf-8'))
        runtime = resources.get('runtime', {})
        for flag in ('darwin_driver_ready', 'flashable', 'hardware_tested',
                     'adapter_ready'):
            if flag in runtime:
                self.assertFalse(runtime[flag], flag)
        # Nothing in this work may assert the GPU runs.
        self.assertNotIn('cmd-db is resolved', self.section())


if __name__ == '__main__':
    unittest.main()
