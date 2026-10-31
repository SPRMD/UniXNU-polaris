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
    def test_checked_in_bundle_matches_current_driver_sources(self):
        manifest = json.loads(
            (ROOT / "research" / "polaris-driver-bundle.json").read_text(
                encoding="utf-8"
            )
        )
        listed = manifest["darwin"]["source_components"]
        expected = MODULE.source_inventory()
        self.assertEqual(listed, expected)
        self.assertFalse(manifest["policy"]["flashable"])
        self.assertFalse(manifest["policy"]["hardware_tested"])

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

    def test_firmware_inventory_matches_extracted_names_case_insensitively(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendor = root / "vendor"
            vendor.mkdir()
            # Stock Polaris packages contain this camera blob with an upper
            # case basename; Linux CI must report it just like Windows does.
            camera = vendor / "CAMERA_ICP.elf"
            camera.write_bytes(b"camera-firmware")
            output = root / "bundle"
            manifest = MODULE.build_bundle(output, vendor, False)
            self.assertEqual(len(manifest["vendor_firmware"]), 1)
            record = manifest["vendor_firmware"][0]
            self.assertEqual(record["name"], "CAMERA_ICP.elf")
            self.assertFalse(record["copied"])
            self.assertEqual(record["darwin_driver"], False)

            # The Polaris WOA package uses the shipped ISP basename with a
            # board-specific suffix; it must be retained as provenance too.
            (vendor / "CAMERA_ICP_AAAAAA.elf").write_bytes(b"isp-firmware")
            second_output = root / "bundle-with-isp"
            second = MODULE.build_bundle(second_output, vendor, False)
            names = {entry["name"] for entry in second["vendor_firmware"]}
            self.assertIn("CAMERA_ICP_AAAAAA.elf", names)

    def test_explicit_copy_preserves_duplicate_vendor_basenames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendor = root / "vendor"
            (vendor / "partition-a").mkdir(parents=True)
            (vendor / "partition-b").mkdir(parents=True)
            (vendor / "partition-a" / "crnv21.bin").write_bytes(b"first")
            (vendor / "partition-b" / "crnv21.bin").write_bytes(b"second")
            output = root / "bundle"
            manifest = MODULE.build_bundle(output, vendor, True)
            records = [entry for entry in manifest["vendor_firmware"]
                       if entry["name"].casefold() == "crnv21.bin"]
            self.assertEqual(len(records), 2)
            paths = {entry["path"] for entry in records}
            self.assertEqual(len(paths), 2)
            for entry in records:
                target = output / entry["path"]
                self.assertEqual(target.stat().st_size, entry["bytes"])


if __name__ == "__main__":
    unittest.main()
