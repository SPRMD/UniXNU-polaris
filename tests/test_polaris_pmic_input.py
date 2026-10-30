import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "drivers" / "PolarisPmicInput"


class PolarisPmicInputSourceTests(unittest.TestCase):
    def test_contract_is_board_gated_and_read_only(self):
        source = (DRIVER / "PolarisPmicInput.cpp").read_text(encoding="utf-8")
        self.assertIn('PE_parse_boot_argn("polaris-pmic-input"', source)
        self.assertIn('compatibleContains(root, "xiaomi,polaris")', source)
        self.assertIn('compatibleContains(root, "qcom,sdm845")', source)
        for text in (
            '"polaris-pmic-input-spmi-writes-performed", false',
            '"polaris-pmic-input-mmio-performed", false',
            '"polaris-pmic-input-gpio-changes-performed", false',
            '"polaris-pmic-input-interrupts-claimed", false',
            '"polaris-pmic-input-hid-published", false',
            '"polaris-pmic-input-power-source-published", false',
            '"polaris-pmic-input-darwin-driver-ready", false',
        ):
            self.assertIn(text, source)
        for forbidden in (
            "ml_io_map", "IODeviceMemory", "IOMemoryDescriptor", "write32",
            "write8", "registerInterrupt", "IOInterruptEventSource",
            "IOHID", "IOPMPowerSource",
        ):
            self.assertNotIn(forbidden, source)

    def test_protocol_has_allowlist_and_no_transport_side_effects(self):
        source = (DRIVER / "PolarisPmicInputProtocol.h").read_text(encoding="utf-8")
        for token in (
            "makeObserverPlan", "allowRead", "decodeKeyLevels",
            "decodeBattery", "kPonPeripheral", "kFuelGaugePeripheral",
        ):
            self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
