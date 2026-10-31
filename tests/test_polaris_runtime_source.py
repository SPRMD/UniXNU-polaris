import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_esp_module():
    spec = importlib.util.spec_from_file_location(
        "make_polaris_ios_esp", ROOT / "scripts" / "make-ios-esp.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
            '"PolarisNfcContract"',
            '"PolarisCameraContract"',
            '"PolarisDisplayContract"',
            '"PolarisA630Probe"',
        ):
            self.assertIn(name, source)
        self.assertIn('polaris_pmic_runtime_static_init', source)
        self.assertIn('polaris_peripheral_contracts_static_init', source)
        self.assertIn('polaris_nfc_contract_static_init', source)
        self.assertIn('polaris_camera_contract_static_init', source)
        self.assertIn('polaris_display_contract_static_init', source)
        self.assertIn('"PolarisPeripheralContracts"', source)
        self.assertIn('polaris-peripheral-probe', source)
        self.assertIn('"PolarisKeysRuntime"', source)
        self.assertIn('"PolarisBatteryRuntime"', source)

    def test_runtime_is_wired_into_board_and_loader_arguments(self):
        board = (ROOT / "board.toml").read_text(encoding="utf-8")
        loader = (ROOT / "scripts" / "make-ios-esp.py").read_text(encoding="utf-8")
        self.assertIn("build-arm-driver.py PolarisRuntime", board)
        self.assertIn("polaris-runtime=1", board)
        self.assertIn("polaris-runtime=1", loader)
        self.assertIn("polaris-nfc-probe=1", loader)
        self.assertIn("polaris-camera-probe=1", loader)
        esp = load_esp_module()
        self.assertNotIn("polaris-touch-hid=1", esp.render_toml(False))
        self.assertNotIn("polariskeys=1", esp.render_toml(False))
        self.assertNotIn("polarisbattery=1", esp.render_toml(False))
        self.assertIn("polaris-touch-hid=1", esp.render_toml(True))
        self.assertIn("polariskeys=1", esp.render_toml(True))
        self.assertIn("polarisbattery=1", esp.render_toml(True))
        self.assertNotIn("polaris-nfc-runtime=1", esp.render_toml(False))
        self.assertNotIn("polaris-camera-runtime=1", esp.render_toml(False))


if __name__ == "__main__":
    unittest.main()
