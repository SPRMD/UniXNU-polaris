import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools" / "derive_runtime_facts.py"
SPEC = importlib.util.spec_from_file_location("derive_runtime_facts", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RuntimeFactsTests(unittest.TestCase):
    def test_allowlist_and_exclusions(self):
        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary)
            (capture / "getprop.txt").write_text(
                "[ro.board.platform]: [sdm845]\n"
                "[ro.boot.bootdevice]: [1d84000.ufshc]\n"
                "[persist.radio.imei]: [must-not-appear]\n"
                "[init.svc.gpu]: [running]\n",
                encoding="utf-8",
            )
            (capture / "dumpsys-display-input.txt").write_text(
                "DisplayDeviceInfo{1080x2160}\n synaptics_dsx\n", encoding="utf-8"
            )
            (capture / "dumpsys-wireless-nfc.txt").write_text(
                "wificond\nNXP NCI\n", encoding="utf-8"
            )
            (capture / "power-supply.txt").write_text(
                "==== /sys/class/power_supply/battery\n", encoding="utf-8"
            )
            (capture / "input-events.txt").write_text(
                "ABS_MT_POSITION_X 00000001\n", encoding="utf-8"
            )
            properties, services = MODULE.parse_getprop(capture / "getprop.txt")
            self.assertEqual(properties["ro.board.platform"], "sdm845")
            self.assertNotIn("persist.radio.imei", properties)
            self.assertEqual(services["gpu"], "running")
            self.assertEqual(MODULE.first_resolution(
                (capture / "dumpsys-display-input.txt").read_text()), "1080x2160")

    def test_report_does_not_copy_raw_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary)
            (capture / "getprop.txt").write_text("[ro.build.product]: [polaris]\n", encoding="utf-8")
            (capture / "input-events.txt").write_text("secret-input-marker\n", encoding="utf-8")
            properties, _ = MODULE.parse_getprop(capture / "getprop.txt")
            report = json.dumps({"properties": properties, "excluded": ["input-events.txt"]})
            self.assertNotIn("secret-input-marker", report)


if __name__ == "__main__":
    unittest.main()
