import importlib.util
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT / "tools" / "make_status_manifest.py"
SPEC = importlib.util.spec_from_file_location("make_status_manifest", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class StatusManifestTests(unittest.TestCase):
    def test_manifest_is_explicitly_non_flashable(self):
        manifest = MODULE.build_manifest(PROJECT)
        self.assertFalse(manifest["flashable"])
        self.assertFalse(manifest["safe_to_flash"])
        self.assertEqual(manifest["installer"]["commands"], [])
        self.assertFalse(manifest["device_access"]["fastboot"])
        self.assertFalse(manifest["build_state"]["hardware_drivers_validated"])

    def test_candidate_userdata_is_not_claimed_as_tested(self):
        manifest = MODULE.build_manifest(PROJECT)
        self.assertTrue(manifest["build_state"]["candidate_userdata_present"])
        self.assertFalse(manifest["build_state"]["candidate_userdata_hardware_tested"])
        self.assertTrue(any("provisional" in item for item in manifest["blockers"]))


if __name__ == "__main__":
    unittest.main()
