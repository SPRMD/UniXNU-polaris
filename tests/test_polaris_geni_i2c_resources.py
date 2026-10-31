from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PolarisGeniI2cResourceTests(unittest.TestCase):
    def test_resource_header_records_cross_checked_polaris_buses(self):
        header = (ROOT / "drivers" / "PolarisGeniI2c" /
                  "PolarisGeniI2cResources.h").read_text(encoding="utf-8")
        for token in (
            "0x0088c000ULL", "0x00a98000ULL", "604", "359",
            "0x28", "0x20", "irq_gpio", "reset_gpio",
            "polaris_geni_i2c_resource_valid",
        ):
            self.assertIn(token, header)
        source = (ROOT / "drivers" / "PolarisPeripheralContracts" /
                  "PolarisPeripheralContracts.cpp").read_text(encoding="utf-8")
        self.assertIn("PolarisGeniI2cResources.h", source)
        self.assertIn('"polaris-peripheral-geni-se3-base"', source)
        self.assertIn('"polaris-peripheral-geni-se14-base"', source)
        self.assertIn('"polaris-peripheral-geni-resource-io-performed", false', source)


if __name__ == "__main__":
    unittest.main()
