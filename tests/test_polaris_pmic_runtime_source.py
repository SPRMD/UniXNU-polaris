import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PolarisPmicRuntimeSourceTests(unittest.TestCase):
    def test_runtime_is_explicitly_gated_and_read_only(self):
        source = (ROOT / "drivers/PolarisPmicRuntime/PolarisPmicRuntime.cpp").read_text()
        self.assertIn('bootArg("polariskeys")', source)
        self.assertIn('bootArg("polarisbattery")', source)
        self.assertIn('HardwareWritesEnabled", kOSBooleanFalse', source)
        self.assertIn('IOLock', source)
        self.assertIn('gPoisoned[apid] = true', source)
        self.assertNotIn('setProperty("HardwareWritesEnabled", kOSBooleanTrue', source)

    def test_fuel_gauge_requires_matching_subtypes(self):
        source = (ROOT / "drivers/PolarisPmicRuntime/PolarisPmicRuntime.cpp").read_text()
        self.assertIn("socSubtype != 0x10", source)
        self.assertIn("infoSubtype != 0x11", source)
        self.assertIn("soc[0] != soc[1]", source)

    def test_keys_require_initial_release_and_fail_closed_each_lane(self):
        source = (ROOT / "drivers/PolarisPmicRuntime/PolarisPmicRuntime.cpp").read_text()
        self.assertIn("candidateValid_[3]", source)
        self.assertIn("live_[3]", source)
        self.assertIn("if (!pressed) live_[index] = true", source)
        self.assertIn("disableKey(0)", source)
        self.assertIn("disableKey(1)", source)
        self.assertIn("disableKey(2)", source)

    def test_build_and_runtime_wiring(self):
        driver_builder = (ROOT / "scripts/build-arm-driver.py").read_text()
        board = (ROOT / "board.toml").read_text()
        runtime = (ROOT / "drivers/PolarisRuntime/PolarisRuntime.cpp").read_text()
        kernel = (ROOT / "scripts/build-platform-kernel.py").read_text()
        self.assertIn("PolarisPmicRuntime", driver_builder)
        self.assertIn("build-arm-driver.py PolarisPmicRuntime", board)
        self.assertIn("__GLOBAL__sub_I_PolarisPmicRuntime.cpp", runtime)
        self.assertIn('"PolarisKeysRuntime"', runtime)
        self.assertIn('"PolarisBatteryRuntime"', runtime)
        self.assertIn("libPolarisPmicRuntime.a", kernel)

    def test_manifest_keeps_flash_gate_closed(self):
        matrix = json.loads((ROOT / "research/polaris-driver-matrix.json").read_text())
        self.assertFalse(matrix["drivers"]["battery"]["userland_ready"])
        self.assertFalse(matrix["drivers"]["buttons"]["userland_ready"])


if __name__ == "__main__":
    unittest.main()
