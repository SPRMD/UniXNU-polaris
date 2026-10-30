import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("make_polaris_package", ROOT / "scripts" / "make-polaris-package.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PolarisPackageBuilderTests(unittest.TestCase):
    def test_package_is_guarded_until_all_gates_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / "esp"
            (esp / "EFI").mkdir(parents=True)
            (esp / "EFI" / "BOOTAA64.EFI").write_bytes(b"efi")
            esp_image = root / "esp.img"
            esp_image.write_bytes(b"image")
            kernel = root / "kernel.macho"
            kernel.write_bytes(b"kernel")
            kernel.with_suffix(".json").write_text(json.dumps({
                "kernel_sha256": MODULE.sha256(kernel),
                "final_configured_link_passed": True,
                "original_components_prelinked": False,
            }), encoding="utf-8")
            output = root / "package"
            manifest = MODULE.build_package(esp, esp_image, kernel, output)
            self.assertFalse(manifest["flashable"])
            self.assertTrue(manifest["blockers"])
            self.assertEqual(json.loads((output / "manifest.json").read_text())["flashable"], False)
            self.assertIn("manifest.flashable", (output / "flash.ps1").read_text(encoding="utf-8"))
            self.assertTrue((output / "SHA256SUMS").is_file())
            self.assertIn("woa_evidence", manifest)
            self.assertTrue(manifest["woa_evidence"]["present"])
            self.assertIn("driver_bundle", manifest)

    def test_firmware_directory_is_packaged_as_an_input_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / "esp"
            esp.mkdir()
            esp_image = root / "esp.img"
            esp_image.write_bytes(b"image")
            kernel = root / "kernel.macho"
            kernel.write_bytes(b"kernel")
            kernel.with_suffix(".json").write_text(json.dumps({
                "kernel_sha256": MODULE.sha256(kernel),
                "final_configured_link_passed": True,
                "original_components_prelinked": False,
            }), encoding="utf-8")
            firmware = root / "firmware"
            firmware.mkdir()
            (firmware / "boot-polaris.img").write_bytes(b"firmware")
            output = root / "package"
            manifest = MODULE.build_package(esp, esp_image, kernel, output, firmware=firmware)
            self.assertFalse(manifest["flashable"])
            self.assertEqual(manifest["inputs"]["firmware"]["path"], "firmware")
            self.assertTrue((output / "firmware" / "boot-polaris.img").is_file())

    def test_explicit_driver_bundle_directory_is_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / "esp"
            esp.mkdir()
            esp_image = root / "esp.img"
            esp_image.write_bytes(b"image")
            kernel = root / "kernel.macho"
            kernel.write_bytes(b"kernel")
            kernel.with_suffix(".json").write_text(json.dumps({
                "kernel_sha256": MODULE.sha256(kernel),
                "final_configured_link_passed": True,
                "original_components_prelinked": False,
            }), encoding="utf-8")
            bundle = root / "bundle"
            bundle.mkdir()
            (bundle / "manifest.json").write_text('{"flashable": false}\n', encoding="utf-8")
            output = root / "package"
            manifest = MODULE.build_package(esp, esp_image, kernel, output,
                                            driver_bundle=bundle)
            self.assertFalse(manifest["flashable"])
            self.assertEqual(manifest["driver_bundle"]["path"], "driver-bundle")
            self.assertTrue((output / "driver-bundle" / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
