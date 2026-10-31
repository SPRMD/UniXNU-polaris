import unittest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "drivers" / "PolarisA630Probe"


class PolarisA630ProbeSourceTests(unittest.TestCase):
    def test_probe_is_opt_in_and_fail_closed(self):
        source = (DRIVER / "PolarisA630Probe.cpp").read_text(encoding="utf-8")
        self.assertIn('PE_parse_boot_argn("polaris-a630-probe"', source)
        self.assertIn('compatibleContains(root, "xiaomi,polaris")', source)
        self.assertIn('compatibleContains(root, "qcom,sdm845")', source)
        self.assertIn('"polaris-a630-gpu-mmio-performed", false', source)
        self.assertIn('"polaris-a630-gpu-writes-performed", false', source)
        self.assertIn('"polaris-a630-resource-contract-valid"', source)
        self.assertIn('"polaris-a630-hardware-writes-allowed"', source)
        self.assertIn('"polaris-a630-firmware-load-allowed"', source)
        self.assertIn('"polaris-a630-dma-allowed"', source)
        self.assertIn('"polaris-a630-gmu-started", false', source)
        self.assertIn('"polaris-a630-smmu-programmed", false', source)
        self.assertIn('"polaris-a630-dma-created", false', source)
        for forbidden in (
            "ml_io_map", "IODeviceMemory", "IOMemoryDescriptor",
            "registerInterrupt", "IOInterruptEventSource", "loadFirmware",
            "write32", "write8",
        ):
            self.assertNotIn(forbidden, source)

    def test_contract_carries_polaris_a630_resources_and_firmware_names(self):
        source = (DRIVER / "PolarisA630Probe.cpp").read_text(encoding="utf-8")
        for value in (
            "/soc/qcom,kgsl-3d0@5000000",
            "/soc/qcom,gmu",
            "/soc/arm,smmu-kgsl@5040000",
            "a630_gmu.bin,a630_sqe.fw,a630_zap.mdt",
            "Adreno 630 / A630v2",
            '"polaris-a630-chip-id-confirmed", false',
            # The stock DT declares exactly one revision; a candidate list here
            # would let a port claim either part without reading anything.
            '"polaris-a630-chip-id-dt-declared", POLARIS_A630_CHIP_ID_DT_DECLARED',
        ):
            self.assertIn(value, source)
        for value in (
            "evidence.gpu.address = gpuRanges[0].address",
            "evidence.gmu.address = gmuRanges[0].address",
            "evidence.smmu.address = smmuRanges[0].address",
        ):
            self.assertIn(value, source)
        self.assertNotIn('setProperty("polaris-a630-chip-id",', source)
        self.assertNotIn("chip-id-candidates", source)

    def test_archive_is_selected_for_darwin_build(self):
        board = (ROOT / "board.toml").read_text(encoding="utf-8")
        builder = (ROOT / "scripts" / "build-arm-driver.py").read_text(encoding="utf-8")
        linker = (ROOT / "scripts" / "build-platform-kernel.py").read_text(encoding="utf-8")
        self.assertIn("build-arm-driver.py PolarisA630Probe", board)
        self.assertIn("'PolarisA630Probe'", builder)
        self.assertIn("libPolarisA630Probe.a", linker)

    def test_portable_policy_is_present_and_fail_closed(self):
        header = (DRIVER / "PolarisA630Policy.h").read_text(encoding="utf-8")
        board = (DRIVER / "PolarisA630Board.h").read_text(encoding="utf-8")
        self.assertIn("polaris_a630_make_plan", header)
        self.assertIn("PolarisA630ReasonHardwareValidationRequired", header)
        self.assertIn("hardware_writes_allowed", header)
        self.assertIn("firmware_load_allowed", header)
        self.assertIn("dma_allowed", header)
        self.assertIn("POLARIS_A630_REFERENCE_ONLY_A642L_CHIP_ID", header)
        self.assertIn("0x06030500u", header)
        for value in (
            "POLARIS_A630_GPU_BASE", "POLARIS_A630_GMU_BASE",
            "POLARIS_A630_SMMU_BASE", "POLARIS_A630_GPU_IRQ_SPI",
            "POLARIS_A630_GMU_HFI_IRQ_SPI", "POLARIS_A630_SMMU_GLOBAL_IRQ0_SPI",
        ):
            self.assertIn(value, board)

    def test_dt_evidence_manifest_is_present_and_fail_closed(self):
        manifest = ROOT / "research" / "polaris-a630-resources.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["board"], "xiaomi,polaris")
        self.assertEqual(data["gpu"]["irq_spi"], 300)
        self.assertEqual(data["gmu"]["irq_spi"]["hfi"], 304)
        self.assertEqual(data["smmu"]["global_irq_spi"], [229, 231])
        self.assertFalse(data["runtime"]["mmio_allowed"])
        self.assertFalse(data["runtime"]["darwin_driver_ready"])


if __name__ == "__main__":
    unittest.main()
