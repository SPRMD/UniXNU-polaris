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
        # Address, IRQ and bus must be read from the DT, not assumed because the
        # board compatible matched.
        for parsed in (
            'getProperty("reg")', 'getProperty("interrupts")',
            "parentIsI2cController", "polaris_nfc_make_plan(evidence)",
            '"polaris-nfc-plan-reason", plan.reason, 32',
            '"polaris-nfc-resource-contract-valid"',
            '"polaris-nfc-i2c-address-observed"',
            '"polaris-nfc-irq-gpio-observed"',
            '"polaris-nfc-i2c-address-matches-candidate"',
            '"polaris-nfc-irq-gpio-matches-candidate"',
        ):
            self.assertIn(parsed, source)
        # A pinctrl state node ("nfc", "nfc_int_active", ...) matches by name but
        # is not the controller, so controller candidates are counted apart.
        self.assertIn("countControllerCandidates", source)
        self.assertIn("firstControllerCandidate", source)
        self.assertIn("isControllerCandidate", source)
        self.assertIn('"polaris-nfc-controller-candidate-nodes"', source)
        self.assertIn("parentIsI2cController", source)
        # A hardcoded "everything is present" evidence block must not exist.
        for overstated in (
            "evidence.bus_present = 1;",
            "evidence.address_valid = 1;",
            "evidence.irq_present = 1;",
        ):
            self.assertNotIn(overstated, source)
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
        # The IMX363 candidate values must come from the shared EDK2 evidence
        # header instead of being re-typed literals in the contract.
        for value in ("POLARIS_IMX363_I2C_ADDRESS", "POLARIS_IMX363_ID_REGISTER",
                      "POLARIS_IMX363_ID_MSB", "POLARIS_IMX363_ID_LSB",
                      "csiphy", "csid"):
            self.assertIn(value, source)
        for literal in ('"polaris-camera-imx363-cci-address-candidate", 0x34U',
                        '"polaris-camera-imx363-id-register", 0x0016U',
                        '"polaris-camera-imx363-id-candidate", 0x0363U'):
            self.assertNotIn(literal, source)
        self.assertIn("PolarisCameraReasonHardwareValidationRequired", policy)
        for reason in (
            "PolarisCameraReasonMissingSensor",
            "PolarisCameraReasonSensorIdentityRequired",
            "PolarisCameraReasonInvalidSensorAddress",
        ):
            self.assertIn(reason, policy)
        # The sensor identity must be scanned from the DT instead of assumed.
        self.assertIn("scanSensorKind(provider, 0, &sensorKind)", source)
        self.assertIn("evidence.sensor_kind = sensorKind;", source)
        self.assertNotIn("evidence.sensor_kind = PolarisCameraSensorImx363;", source)
        self.assertIn('"polaris-camera-plan-reason", plan.reason, 32', source)
        self.assertIn('"polaris-camera-sensor-identity-confirmed", false', source)
        self.assertIn('"polaris-camera-sensor-address-confirmed", false', source)
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
