import unittest
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
            "0x06030000,0x06030001",
            '"polaris-a630-chip-id-confirmed", false',
        ):
            self.assertIn(value, source)
        self.assertNotIn('setProperty("polaris-a630-chip-id",', source)

    def test_archive_is_selected_for_darwin_build(self):
        board = (ROOT / "board.toml").read_text(encoding="utf-8")
        builder = (ROOT / "scripts" / "build-arm-driver.py").read_text(encoding="utf-8")
        linker = (ROOT / "scripts" / "build-platform-kernel.py").read_text(encoding="utf-8")
        self.assertIn("build-arm-driver.py PolarisA630Probe", board)
        self.assertIn("'PolarisA630Probe'", builder)
        self.assertIn("libPolarisA630Probe.a", linker)


if __name__ == "__main__":
    unittest.main()
