import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_root_stage", ROOT / "scripts" / "check-root-stage.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RootStageTests(unittest.TestCase):
    def test_current_tree_reports_local_userland_inputs_without_claiming_ready(self):
        report = MODULE.check(
            ROOT,
            ROOT.parents[1] / "upstream" / "UniXNU",
            ROOT.parents[1] / "inputs" / "ipsw",
        )
        self.assertFalse(report["device_access"])
        self.assertFalse(report["ready_for_phone_boot"])
        self.assertTrue(report["ready_for_userdata_build"])
        self.assertTrue(report["root_images"]["os_dmg_present"])
        self.assertTrue(report["root_images"]["system_os_dmg_present"])
        self.assertTrue(report["userdata_artifact"]["present"])
        self.assertTrue(report["userdata_artifact"]["facts"]["valid"])
        self.assertIn("Darwin 23 compiler tools are unavailable on this host", report["prelink_blockers"])
        self.assertNotIn("OS/SystemOS DMGs are absent; no userdata root can be assembled", report["blockers"])

    def test_macho_facts_reject_non_macho(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-macho"
            path.write_bytes(b"fixture")
            self.assertFalse(MODULE.macho_facts(path)["mach_o_arm64"])

    def test_report_is_json_serializable(self):
        report = MODULE.check(
            ROOT,
            ROOT.parents[1] / "upstream" / "UniXNU",
            ROOT.parents[1] / "inputs" / "ipsw",
        )
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
