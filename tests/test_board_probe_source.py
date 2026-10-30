import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "drivers" / "PolarisBoardProbe" / "PolarisBoardProbe.cpp"
PLIST = ROOT / "drivers" / "PolarisBoardProbe" / "Info.plist"


class PolarisBoardProbeSourceTests(unittest.TestCase):
    def test_is_opt_in_and_read_only(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('PE_parse_boot_argn ("polaris-board-probe"', source)
        self.assertIn('"xiaomi,polaris"', source)
        self.assertIn('"qcom,sdm845"', source)
        self.assertIn('"polaris-board-mmio-performed", false', source)
        for forbidden in ("IOMemoryDescriptor", "IODeviceMemory", "map (", "withPhysicalAddress", "read32", "write32"):
            self.assertNotIn(forbidden, source)

    def test_personality_matches_arm_io(self):
        plist = PLIST.read_text(encoding="utf-8")
        self.assertIn("<string>IOPlatformDevice</string>", plist)
        self.assertIn("<key>IONameMatch</key><string>arm-io</string>", plist)


if __name__ == "__main__":
    unittest.main()
