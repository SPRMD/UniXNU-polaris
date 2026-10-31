import importlib.util
import hashlib
import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_root_stage", ROOT / "scripts" / "check-root-stage.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RootStageTests(unittest.TestCase):
    def test_current_tree_reports_local_userland_inputs_without_claiming_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            root = project / "repo"
            upstream = project / "upstream" / "UniXNU"
            inputs = project / "inputs" / "ipsw"
            (root / "configs").mkdir(parents=True)
            shutil.copy2(ROOT / "board.toml", root / "board.toml")
            shutil.copy2(
                ROOT / "configs" / "polaris_prelink_defconfig",
                root / "configs" / "polaris_prelink_defconfig",
            )
            (upstream / "scripts").mkdir(parents=True)
            (upstream / "scripts" / "build-mockfs-fixture.py").write_text("# fixture\n")
            patch_dir = upstream / "patches" / "xnu"
            patch_dir.mkdir(parents=True)
            for name in (
                "mockfs-intermediate-lookup.patch",
                "mockfs-memory-device-width.patch",
                "mockfs-statfs.patch",
                "mockfs-test-file.patch",
                "mockfs-typed-allocation.patch",
            ):
                (patch_dir / name).write_text("# fixture\n")
            inputs.mkdir(parents=True)
            (inputs / "044-76040-038.dmg").write_bytes(b"OS fixture")
            (inputs / "044-76034-038.dmg").write_bytes(b"SystemOS fixture")
            userdata = root / "out" / "polaris" / "userdata" / "userdata-root.img"
            userdata.parent.mkdir(parents=True)
            header = bytearray(4096)
            header[:8] = b"SHNGROOT"
            struct.pack_into("<IIQ", header, 8, 1, 2, 4096)
            header[4064:4096] = hashlib.sha256(header[:4064]).digest()
            userdata.write_bytes(header)

            report = MODULE.check(root, upstream, inputs)
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
        report = MODULE.check(ROOT, ROOT.parents[1] / "upstream" / "UniXNU",
                              ROOT.parents[1] / "inputs" / "ipsw")
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
