import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PolarisPeripheralContractTests(unittest.TestCase):
    def test_contract_is_board_gated_and_has_no_hardware_side_effects(self):
        source = (ROOT / "drivers" / "PolarisPeripheralContracts" /
                  "PolarisPeripheralContracts.cpp").read_text(encoding="utf-8")
        self.assertIn('PE_parse_boot_argn("polaris-peripheral-probe"', source)
        self.assertIn('xiaomi,polaris', source)
        self.assertIn('qcom,sdm845', source)
        self.assertIn('polaris-peripheral-hardware-io", false', source)
        self.assertIn('polaris-peripheral-firmware-loaded", false', source)
        self.assertIn('polaris-peripheral-dma-created", false', source)
        self.assertIn('polaris-peripheral-network-device-published", false', source)
        self.assertIn('polaris-peripheral-camera-device-published", false', source)
        self.assertIn('polaris-peripheral-nfc-device-published", false', source)
        self.assertIn('PolarisTransportSelfTest::run()', source)

    def test_board_runtime_bundle_and_workflow_include_archive(self):
        board = (ROOT / "board.toml").read_text(encoding="utf-8")
        runtime = (ROOT / "drivers" / "PolarisRuntime" /
                   "PolarisRuntime.cpp").read_text(encoding="utf-8")
        linker = (ROOT / "scripts" / "build-platform-kernel.py").read_text(encoding="utf-8")
        builder = (ROOT / "scripts" / "build-arm-driver.py").read_text(encoding="utf-8")
        bundle = (ROOT / "scripts" / "make-polaris-driver-bundle.py").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "polaris-build.yml").read_text(encoding="utf-8")
        self.assertIn("build-arm-driver.py PolarisPeripheralContracts", board)
        self.assertIn("polaris-peripheral-probe=1", board)
        self.assertIn('"PolarisPeripheralContracts"', runtime)
        self.assertIn("libPolarisPeripheralContracts.a", linker)
        self.assertIn("'PolarisPeripheralContracts'", builder)
        self.assertIn('"PolarisPeripheralContracts"', bundle)
        self.assertIn("polaris-peripheral-contracts", workflow)


if __name__ == "__main__":
    unittest.main()
