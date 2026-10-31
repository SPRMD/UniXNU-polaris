import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StatusManifestTests(unittest.TestCase):
    """Keep the status contract local to this checkout.

    The old version imported a workspace-level helper that is absent from a
    GitHub checkout and could walk broken symlinks.  The package builder and
    hardware contract are the canonical local status sources now.
    """

    def test_contract_defaults_to_disabled_until_verified(self):
        contract = json.loads(
            (ROOT / "research" / "polaris-hardware-contract.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            contract["policy"]["default_driver_mode"], "disabled-until-verified"
        )
        self.assertFalse(contract["policy"]["android_binaries_are_darwin_drivers"])
        self.assertTrue(contract["policy"]["required_for_flash"])
        self.assertTrue(all(not item["enabled"] for item in contract["subsystems"].values()))
        for name, item in contract["subsystems"].items():
            for evidence in item.get("evidence", []):
                self.assertTrue(
                    (ROOT / evidence).is_file(),
                    f"{name} evidence is outside the repository or missing: {evidence}",
                )

    def test_package_builder_contains_no_unconditional_flash_state(self):
        source = (ROOT / "scripts" / "make-polaris-package.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"flashable": flashable', source)
        self.assertIn("manifest.flashable", source)


if __name__ == "__main__":
    unittest.main()
