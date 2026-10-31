import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "drivers" / "PolarisHardwareServices"


class PolarisHardwareServicesSourceTests(unittest.TestCase):
    def test_probe_is_opt_in_and_fail_closed(self):
        source = (DRIVER / "PolarisHardwareServices.cpp").read_text(encoding="utf-8")
        self.assertIn('PE_parse_boot_argn("polaris-hw-probe"', source)
        self.assertIn('compatibleContains(root, "xiaomi,polaris")', source)
        self.assertIn('compatibleContains(root, "qcom,sdm845")', source)
        self.assertIn('"polaris-hw-probe-mmio-performed", false', source)
        self.assertIn('"polaris-hw-probe-writes-performed", false', source)
        self.assertIn('"polaris-hw-probe-firmware-loaded", false', source)
        self.assertIn('"polaris-hw-probe-dma-created", false', source)
        for forbidden in (
            "ml_io_map", "IODeviceMemory", "IOMemoryDescriptor", "write32",
            "write8", "registerInterrupt", "setPowerState", "IOInterruptEventSource",
        ):
            self.assertNotIn(forbidden, source)

    def test_inventory_covers_requested_non_fingerprint_subsystems(self):
        source = (DRIVER / "PolarisHardwareServices.cpp").read_text(encoding="utf-8")
        for name in (
            "kPowerKeys", "kDisplay", "kTouch", "kBattery", "kGpu",
            "kWifi", "kBluetooth", "kNfc", "kCamera",
        ):
            self.assertIn(name, source)
        for compatible in (
            "synaptics,dsx-i2c-force", "focaltech,ft5x46", "qcom,nq-nci",
            "qca,wcn3990", "qcom,kgsl-3d0", "qcom,fg-gen3",
        ):
            self.assertIn(compatible, source)
        self.assertIn("resource-only; no Darwin transport", source)
        self.assertIn("darwin-driver-ready", source)

    def test_wifi_and_bluetooth_match_sets_are_disjoint(self):
        """A Bluetooth node must never be counted as a WiFi resource.

        In the reference Polaris DTB the only nodes containing the token "wcn"
        are Bluetooth-side (bt_wcn3990 and the SLIMbus wcn3990 slave), so the
        old "wcn" WiFi token inflated the WiFi count with Bluetooth nodes.
        """
        source = (DRIVER / "PolarisHardwareServices.cpp").read_text(encoding="utf-8")
        wifi_line = next(line for line in source.splitlines()
                         if "wifiNames[]" in line)
        self.assertNotIn('"wcn"', wifi_line)
        self.assertIn('"icnss"', wifi_line)
        self.assertIn('"wlan"', wifi_line)
        self.assertIn('"qcom,icnss"', source)
        bluetooth_line = next(line for line in source.splitlines()
                              if "bluetoothNames[]" in line)
        self.assertIn('"wcn3990"', bluetooth_line)
        self.assertIn('"qca,wcn3990"', source)

    def test_personality_is_limited_to_arm_io(self):
        plist = (DRIVER / "Info.plist").read_text(encoding="utf-8")
        self.assertIn("<string>IOPlatformDevice</string>", plist)
        self.assertIn("<key>IONameMatch</key><string>arm-io</string>", plist)


if __name__ == "__main__":
    unittest.main()
