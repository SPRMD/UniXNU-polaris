import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "make_polaris_driver_bundle", ROOT / "scripts" / "make-polaris-driver-bundle.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PolarisDriverBundleTests(unittest.TestCase):
    def test_metadata_bundle_never_copies_vendor_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendor = root / "vendor"
            vendor.mkdir()
            (vendor / "a630_gmu.bin").write_bytes(b"firmware")
            output = root / "bundle"
            manifest = MODULE.build_bundle(output, vendor, False)
            self.assertFalse(manifest["policy"]["flashable"])
            self.assertEqual(manifest["vendor_firmware"][0]["copied"], False)
            self.assertFalse((output / "vendor").exists())
            self.assertFalse(str(output) in (output / "manifest.json").read_text())

    def test_explicit_copy_is_hashed_and_still_non_flashable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendor = root / "vendor"
            vendor.mkdir()
            (vendor / "a630_sqe.fw").write_bytes(b"sqe")
            output = root / "bundle"
            manifest = MODULE.build_bundle(output, vendor, True)
            self.assertFalse(manifest["policy"]["flashable"])
            self.assertTrue((output / "vendor" / "a630_sqe.fw").is_file())
            self.assertTrue(manifest["vendor_firmware"][0]["copied"])
            self.assertIn("sha256", manifest["vendor_firmware"][0])
            loaded = json.loads((output / "manifest.json").read_text())
            self.assertFalse(loaded["policy"]["hardware_tested"])


if __name__ == "__main__":
    unittest.main()
