from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PolarisNfcCameraContractTests(unittest.TestCase):
    def test_nfc_contract_is_gated_and_fail_closed(self):
        driver = ROOT / "drivers" / "PolarisNfcContract"
        source = (driver / "PolarisNfcContract.cpp").read_text(encoding="utf-8")
        policy = (driver / "PolarisNfcPolicy.h").read_text(encoding="utf-8")
        self.assertIn('PE_parse_boot_argn("polaris-nfc-probe"', source)
        self.assertIn('"qcom,nq-nci"', source)
        self.assertIn('"polaris-nfc-i2c-writes-allowed"', source)
        self.assertIn('"polaris-nfc-darwin-driver-ready", false', source)
        self.assertIn("PolarisNfcReasonHardwareValidationRequired", policy)
        for forbidden in (
            "IOI2C", "registerInterrupt", "IOInterruptEventSource",
            "write32", "write8", "loadFirmware", "IOMemoryDescriptor",
            "IOMemoryMap", "createDMA",
        ):
            self.assertNotIn(forbidden, source)

    def test_camera_contract_is_gated_and_fail_closed(self):
        driver = ROOT / "drivers" / "PolarisCameraContract"
        source = (driver / "PolarisCameraContract.cpp").read_text(encoding="utf-8")
        policy = (driver / "PolarisCameraPolicy.h").read_text(encoding="utf-8")
        self.assertIn('PE_parse_boot_argn("polaris-camera-probe"', source)
        self.assertIn('"sony,imx363"', source)
        self.assertIn('"polaris-camera-sensor-power-allowed"', source)
        self.assertIn('"polaris-camera-darwin-driver-ready", false', source)
        for value in ("0x34", "0x0016", "0x0363", "csiphy", "csid"):
            self.assertIn(value, source)
        self.assertIn("PolarisCameraReasonHardwareValidationRequired", policy)
        for forbidden in (
            "IOI2C", "registerInterrupt", "IOInterruptEventSource",
            "write32", "write8", "loadFirmware", "IOMemoryDescriptor",
            "IOMemoryMap", "createDMA",
        ):
            self.assertNotIn(forbidden, source)

    def test_contract_archives_and_runtime_gates_are_wired(self):
        board = (ROOT / "board.toml").read_text(encoding="utf-8")
        builder = (ROOT / "scripts" / "build-arm-driver.py").read_text(encoding="utf-8")
        linker = (ROOT / "scripts" / "build-platform-kernel.py").read_text(encoding="utf-8")
        bundle = (ROOT / "scripts" / "make-polaris-driver-bundle.py").read_text(encoding="utf-8")
        runtime = (ROOT / "drivers" / "PolarisRuntime" / "PolarisRuntime.cpp").read_text(encoding="utf-8")
        loader = (ROOT / "scripts" / "make-ios-esp.py").read_text(encoding="utf-8")
        for component in ("PolarisNfcContract", "PolarisCameraContract"):
            self.assertIn("build-arm-driver.py " + component, board)
            self.assertIn("'" + component + "'", builder)
            self.assertIn('"' + component + '"', runtime)
            self.assertIn(component, bundle)
        self.assertIn("libPolarisNfcContract.a", linker)
        self.assertIn("libPolarisCameraContract.a", linker)
        self.assertIn("polaris-nfc-probe=1", loader)
        self.assertIn("polaris-camera-probe=1", loader)
        self.assertNotIn("polaris-nfc-runtime=1", loader)
        self.assertNotIn("polaris-camera-runtime=1", loader)


if __name__ == "__main__":
    unittest.main()
