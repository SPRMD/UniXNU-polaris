import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "drivers" / "PolarisTransportContracts"


class PolarisTransportContractTests(unittest.TestCase):
    def test_protocol_headers_and_service_are_present(self):
        for name in (
            "PolarisQcaProtocol.h", "PolarisWlfwProtocol.h",
            "PolarisNci.h", "PolarisCciProtocol.h", "PolarisPmicProtocol.h",
            "PolarisH4Protocol.h", "PolarisProtocolSelfTest.h",
        ):
            self.assertTrue((DRIVER / name).is_file(), name)
        source = (DRIVER / "PolarisTransportContracts.cpp").read_text(encoding="utf-8")
        self.assertIn('PE_parse_boot_argn("polaris-transport-probe"', source)
        self.assertIn('setProperty("polaris-transport-hardware-io", false)', source)
        self.assertIn('setProperty("polaris-transport-darwin-driver-ready", false)', source)
        self.assertIn('setProperty("polaris-transport-pmic-spmi-read-only", true)', source)
        self.assertIn('setProperty("polaris-transport-wireless-chip"', source)
        self.assertIn('setProperty("polaris-transport-wifi-firmware-candidates"', source)
        self.assertIn('setProperty("polaris-transport-bluetooth-firmware-candidates"', source)
        self.assertIn('setProperty("polaris-transport-self-test-mask"', source)
        self.assertIn('setProperty("polaris-transport-self-test-failures"', source)
        self.assertIn('PolarisTransportSelfTest::run()', source)
        self.assertIn('polaris-wireless-runtime=1', source)
        for forbidden in ("IODeviceMemory", "IOMemoryDescriptor", "registerInterrupt",
                          "write32", "write8", "IOWorkLoop", "loadFirmware"):
            self.assertNotIn(forbidden, source)

    def test_qca_firmware_session_is_bounded_and_side_effect_free(self):
        header = (DRIVER / "PolarisH4Protocol.h").read_text(encoding="utf-8")
        for symbol in (
            "class QcaFirmwareSession", "begin(", "acceptVersion(",
            "startFile(", "nextSegment(", "acceptSegmentAck(",
            "kMaxFileBytes", "AwaitVersion", "AwaitSegment", "Complete",
            "Failed",
        ):
            self.assertIn(symbol, header)
        for forbidden in (
            "IODeviceMemory", "IOMemoryDescriptor", "registerInterrupt",
            "IOWorkLoop", "loadFirmware", "openUART", "write32", "write8",
        ):
            self.assertNotIn(forbidden, header)

    def test_ci_compiles_protocol_host_test(self):
        workflow = (ROOT / ".github" / "workflows" / "polaris-build.yml").read_text(encoding="utf-8")
        self.assertIn("tests/polaris_transport_protocols_test.cpp", workflow)
        self.assertIn("out/host-tests/polaris_transport_protocols_test", workflow)

    def test_service_personality_is_platform_only(self):
        plist = (DRIVER / "Info.plist").read_text(encoding="utf-8")
        self.assertIn("PolarisTransportContracts", plist)
        self.assertIn("IOPlatformDevice", plist)


if __name__ == "__main__":
    unittest.main()
