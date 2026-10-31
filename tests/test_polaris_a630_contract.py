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

    def test_iommus_are_not_parsed_as_ranges(self):
        # A {phandle, sid} tuple read as {address, size} would turn SID 0 into a
        # zero-size range and silently drop it; the probe needs its own reader.
        source = PROBE.read_text()
        self.assertIn("readStreamIds", source)
        self.assertIn("readStreamIds(user, userSids, 2)", source)
        self.assertIn("readStreamIds(secure, secureSids, 2)", source)
        self.assertIn("be32(bytes + offset + 4)", source)


if __name__ == "__main__":
    unittest.main()
