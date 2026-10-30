import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "import-polaris-woa-evidence.py"
SPEC = importlib.util.spec_from_file_location("woa_evidence", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PolarisWoaEvidenceTests(unittest.TestCase):
    def test_manifest_is_metadata_only_and_never_copies_binaries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            woa = root / "WOA-Drivers"
            path = woa / "components/SDM845/Device/Xiaomi/Polaris/SynapticsTouch"
            path.mkdir(parents=True)
            (path / "SynapticsTouch.sys").write_bytes(b"private")
            (path / "SynapticsTouch.inf_").write_text("reference", encoding="utf-8")
            manifest = MODULE.build_manifest(woa_root=woa, woa_polaris_root=root / "docs",
                                             vendor_root=root / "vendor")
            self.assertFalse(manifest["policy"]["copy_vendor_binaries"])
            files = manifest["subsystems"]["touch"]["files"]
            self.assertEqual({item["name"] for item in files}, {"SynapticsTouch.sys", "SynapticsTouch.inf_"})
            self.assertTrue(all(item["copied"] is False for item in files))
            self.assertTrue(all(item["darwin_reusable"] is False for item in files))
            payload = json.dumps(manifest)
            self.assertIn("SynapticsTouch.sys", payload)
            self.assertNotIn("private", payload)

    def test_local_repositories_are_reported_without_absolute_user_paths(self):
        manifest = MODULE.build_manifest()
        encoded = json.dumps(manifest)
        self.assertEqual(manifest["board"], "xiaomi,polaris")
        self.assertFalse(manifest["policy"]["flashable"])
        self.assertNotIn(str(ROOT), encoded)
        self.assertIn("a630_gmu.bin", encoded)
        self.assertIn("crbtfw20.tlv", encoded)
        self.assertIn("com.qti.sensormodule.imx363.bin", encoded)

    def test_subsystems_are_marked_reference_only(self):
        manifest = MODULE.build_manifest()
        for name in ("touch", "camera", "gpu", "wifi", "bluetooth", "battery", "nfc"):
            item = manifest["subsystems"][name]
            self.assertFalse(item["darwin_driver"])
            self.assertFalse(item["copied"])
            self.assertIn("darwin_status", item)

    def test_polaris_windows_checklist_is_hashed_and_kept_as_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docs = root / "docs" / "guide"
            docs.mkdir(parents=True)
            (docs / "status.md").write_text(
                "- [x] Battery status\n- [ ] Camera\n- [X] Wi-Fi\n",
                encoding="utf-8",
            )
            manifest = MODULE.build_manifest(
                woa_root=root / "WOA-Drivers",
                woa_polaris_root=root / "docs",
                vendor_root=root / "vendor",
            )
            features = manifest["woa_polaris_status"]["features"]
            self.assertTrue(features["battery_status"]["working_on_windows"])
            self.assertFalse(features["camera"]["working_on_windows"])
            self.assertTrue(features["wi_fi"]["working_on_windows"])
            self.assertIsNotNone(manifest["woa_polaris_status"]["sha256"])
            self.assertFalse(manifest["woa_polaris_status"]["darwin_driver"])


if __name__ == "__main__":
    unittest.main()
