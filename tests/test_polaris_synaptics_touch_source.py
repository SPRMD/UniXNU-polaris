import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "drivers" / "PolarisSynapticsTouch"


class PolarisSynapticsTouchSourceTests(unittest.TestCase):
    def test_iokit_contract_is_strictly_gated(self):
        source = (DRIVER / "PolarisSynapticsTouch.cpp").read_text(encoding="utf-8")
        self.assertIn('PE_parse_boot_argn("polaris-rmi4-touch"', source)
        self.assertIn('compatibleContains(root, "xiaomi,polaris")', source)
        self.assertIn('compatibleContains(root, "qcom,sdm845")', source)
        self.assertIn('"synaptics,dsx-i2c-force"', source)
        self.assertIn('"polaris-rmi4-touch-pdt-read", false', source)
        self.assertIn('"polaris-rmi4-touch-reset-performed", false', source)
        self.assertIn('"polaris-rmi4-touch-mmio-performed", false', source)
        self.assertIn('"polaris-rmi4-touch-hid-registered", false', source)
        for forbidden in (
            "IODeviceMemory", "IOMemoryDescriptor", "registerInterrupt",
            "IOInterruptEventSource", "write32", "write8", "IOHIDDevice",
        ):
            self.assertNotIn(forbidden, source)

    def test_runtime_transport_is_separately_gated_and_bounded(self):
        source = (DRIVER / "PolarisTouchRuntime.c").read_text(encoding="utf-8")
        self.assertIn('"polaris-touch-runtime"', source)
        self.assertIn('"polaristouchhid"', source)
        self.assertIn('TLMM_NORTH_PA 0x03900000UL', source)
        self.assertIn('SDA_CFG (33u * 0x1000u)', source)
        self.assertIn('SCL_CFG (34u * 0x1000u)', source)
        self.assertIn('I2C_ADDRESS 0x20u', source)
        self.assertIn('POLARIS_TOUCH_MAX_SLOTS 10u', source)
        self.assertIn('length <= 96u', source)
        self.assertIn('restore_pads()', source)
        self.assertIn('polaris_touch_runtime_set_sink', source)

    def test_runtime_build_is_in_board_archive_list(self):
        board = (ROOT / "board.toml").read_text(encoding="utf-8")
        self.assertIn('build-polaris-touch-runtime.py', board)
        builder = (ROOT / "scripts" / "build-platform-kernel.py").read_text(encoding="utf-8")
        self.assertIn('libPolarisTouchRuntime.a', builder)

    def test_protocol_header_is_bounded_and_rmi4_specific(self):
        header = (DRIVER / "SynapticsRmi4Protocol.h").read_text(encoding="utf-8")
        for symbol in (
            "polaris_rmi4_parse_pdt", "polaris_rmi4_parse_contact",
            "polaris_rmi4_parse_contacts", "POLARIS_RMI4_F12_FRAME_BYTES",
            "POLARIS_RMI4_MAX_SLOTS",
        ):
            self.assertIn(symbol, header)
        self.assertIn("length != slots * POLARIS_RMI4_F12_FRAME_BYTES", header)

    def test_ci_host_test_uses_rmi4_name(self):
        workflow = (ROOT / ".github" / "workflows" / "polaris-build.yml").read_text(encoding="utf-8")
        self.assertIn("tests/synaptics_rmi4_protocol_test.cpp", workflow)
        self.assertIn("out/host-tests/synaptics_rmi4_protocol_test", workflow)
        self.assertNotIn("synaptics_s3330_protocol_test", workflow)
    def test_personality_is_a_platform_contract_only(self):
        plist = (DRIVER / "Info.plist").read_text(encoding="utf-8")
        self.assertIn("<string>IOPlatformDevice</string>", plist)
        self.assertIn("<string>PolarisSynapticsTouch</string>", plist)


if __name__ == "__main__":
    unittest.main()



