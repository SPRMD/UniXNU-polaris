import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe-polaris-resources.py"
SPEC = importlib.util.spec_from_file_location("probe_polaris_resources", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PolarisResourceTests(unittest.TestCase):
    def test_expected_contract_matches_fixture(self):
        entry = {
            "nodes": [
                {"name": name, "compatible": [compat], "reg": reg,
                 "interrupts": interrupts or []}
                for role, (name, compat, reg, interrupts) in MODULE.EXPECTED.items()
            ] + [
                {"name": "bt_wcn3990", "compatible": ["qca,wcn3990"], "reg": [], "interrupts": []},
                {"name": "wlan_fw_region@0x8e300000", "compatible": ["removed-dma-pool"],
                 "reg": [0, 0x8E300000, 0, 0x100000], "interrupts": []},
            ]
        }
        self.assertEqual(MODULE.check_entry(entry), [])

    def test_mismatch_fails_closed(self):
        entry = {"nodes": []}
        errors = MODULE.check_entry(entry)
        self.assertTrue(errors)
        self.assertIn("ufs: missing node ufshc@1d84000", errors)


if __name__ == "__main__":
    unittest.main()
