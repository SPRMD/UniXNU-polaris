import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_polaris_driver_bundle", ROOT / "scripts" / "check-polaris-driver-bundle.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

MAKE_SPEC = importlib.util.spec_from_file_location(
    "make_polaris_driver_bundle", ROOT / "scripts" / "make-polaris-driver-bundle.py"
)
MAKE = importlib.util.module_from_spec(MAKE_SPEC)
assert MAKE_SPEC.loader is not None
MAKE_SPEC.loader.exec_module(MAKE)


class PolarisDriverBundleCheckerTests(unittest.TestCase):
    def test_checker_accepts_current_metadata_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "bundle"
            MAKE.build_bundle(bundle, None, False)
            manifest = MODULE.verify_manifest(bundle, ROOT)
            self.assertFalse(manifest["policy"]["flashable"])
            self.assertGreater(MODULE.verify_sums(bundle), 0)

    def test_checker_rejects_tampered_checksum_or_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendor = root / "vendor"
            vendor.mkdir()
            (vendor / "a630_sqe.fw").write_bytes(b"sqe")
            bundle = root / "bundle"
            MAKE.build_bundle(bundle, vendor, True)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["policy"]["flashable"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE.verify_manifest(bundle, None)

    def test_checker_rejects_windows_source_paths_without_source_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle"
            MAKE.build_bundle(bundle, None, False)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["darwin"]["source_components"][0]["path"] = (
                r"C:\\Windows\\System32\\driver.sys"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE.verify_manifest(bundle, None)


if __name__ == "__main__":
    unittest.main()
