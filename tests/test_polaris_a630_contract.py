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
    text = BOARD.read_text()
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
        cls.resources = json.loads(RESOURCES.read_text())

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
        self.assertNotIn("chip-id-candidates", PROBE.read_text())

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
        source = PROBE.read_text()
        for guard in ("polaris-a630-gpu-mmio-performed", "polaris-a630-gmu-started",
                      "polaris-a630-smmu-programmed", "polaris-a630-dma-created",
                      "polaris-a630-darwin-driver-ready"):
            self.assertIn(guard, source)

    def test_driver_matrix_does_not_claim_gpu_readiness(self):
        matrix = json.loads(MATRIX.read_text())
        gpu = matrix["drivers"]["gpu_adreno630"]
        self.assertFalse(gpu["enabled_by_default"])
        self.assertFalse(gpu["userland_ready"])

    def test_supporting_windows_come_from_their_own_dt_nodes(self):
        source = PROBE.read_text()
        for node in ('"/soc/qcom,gcc@100000"', '"/soc/interrupt-controller@0xb220000"',
                     '"/soc/qcom,sde_rscc@af20000"'):
            self.assertIn(node, source)
        windows = self.resources["supporting_windows"]
        self.assertEqual(int(windows["gcc"]["base"], 16), value("POLARIS_A630_GCC_BASE"))
        self.assertEqual(int(windows["pdc"]["base"], 16), value("POLARIS_A630_PDC_BASE"))
        self.assertEqual(int(windows["rscc"]["base"], 16), value("POLARIS_A630_RSCC_BASE"))

    def test_record_completeness_is_not_readiness(self):
        source = PROBE.read_text()
        # A complete resource record must not imply a usable GPU.
        self.assertIn("polaris-a630-resource-record-complete", source)
        self.assertIn('setProperty("polaris-a630-darwin-driver-ready", false)', source)
        runtime = self.resources["runtime"]
        self.assertFalse(runtime["darwin_driver_ready"])

    def test_iommus_are_not_parsed_as_ranges(self):
        # A {phandle, sid} tuple read as {address, size} would turn SID 0 into a
        # zero-size range and silently drop it; the probe needs its own reader.
        source = PROBE.read_text()
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
        cls.resources = json.loads(RESOURCES.read_text())

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
        gap = GAP.read_text()
        self.assertIn("lpacSid", gap)
        self.assertIn("still unresolved", gap)

    def test_quirks_are_recorded_as_booleans_not_values(self):
        quirks = self.resources["gpu"]["quirks"]
        self.assertIn("gpu-quirk-hfi-use-reg", quirks)
        self.assertIn("gpu-quirk-secvid-set-once", quirks)
        self.assertIn("no-nap", quirks)


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


if __name__ == "__main__":
    unittest.main()
