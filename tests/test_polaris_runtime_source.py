import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PolarisRuntimeSourceTests(unittest.TestCase):
    def test_runtime_is_explicitly_gated_and_starts_contract_services(self):
        source = (ROOT / "drivers" / "PolarisRuntime" / "PolarisRuntime.cpp").read_text(encoding="utf-8")
        self.assertIn('PE_parse_boot_argn("polaris-runtime"', source)
        self.assertIn('IOService::nameMatching("arm-io")', source)
        for name in (
            '"PolarisBoardProbe"',
            '"PolarisHardwareServices"',
            '"PolarisPmicInput"',
            '"PolarisSynapticsTouch"',
            '"PolarisTransportContracts"',
            '"PolarisA630Probe"',
        ):
            self.assertIn(name, source)
        self.assertIn('polaris_pmic_runtime_static_init', source)
        self.assertIn('"PolarisKeysRuntime"', source)
        self.assertIn('"PolarisBatteryRuntime"', source)

    def test_runtime_is_wired_into_board_and_loader_arguments(self):
        board = (ROOT / "board.toml").read_text(encoding="utf-8")
        loader = (ROOT / "scripts" / "make-ios-esp.py").read_text(encoding="utf-8")
        self.assertIn("build-arm-driver.py PolarisRuntime", board)
        self.assertIn("polaris-runtime=1", board)
        self.assertIn("polaris-runtime=1", loader)
        self.assertNotIn("polariskeys=1", loader)
        self.assertNotIn("polarisbattery=1", loader)


if __name__ == "__main__":
    unittest.main()
