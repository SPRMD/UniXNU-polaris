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
CHECK_SPEC = importlib.util.spec_from_file_location(
    "check_polaris_package", ROOT / "scripts" / "check-polaris-package.py"
)
CHECK = importlib.util.module_from_spec(CHECK_SPEC)
assert CHECK_SPEC.loader is not None
CHECK_SPEC.loader.exec_module(CHECK)


class PolarisPackageBuilderTests(unittest.TestCase):
    def test_split_root_keeps_same_named_inputs_separate_and_checks_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / 'esp'
            payload = esp / 'EFI/UniXNU/Payloads'
            payload.mkdir(parents=True)
            kernel = root / 'kernel.macho'
            kernel.write_bytes(b'kernel')
            (payload / 'kernel.macho').write_bytes(b'kernel')
            sources = []
            for role, content in (('esp', b'fat'), ('root', b'SHNGROOT'), ('firmware', b'boot')):
                parent = root / ('input-' + role)
                parent.mkdir()
                source = parent / 'image.img'
                source.write_bytes(content)
                sources.append(source)
            esp_image, darwin, firmware = sources
            output = root / 'package'
            manifest = MODULE.build_package(esp, esp_image, kernel, output,
                                             firmware=firmware, darwin_root=darwin)
            self.assertEqual((output / 'esp.img').read_bytes(), b'fat')
            self.assertEqual((output / 'darwin-root.img').read_bytes(), b'SHNGROOT')
            self.assertEqual((output / 'firmware/image.img').read_bytes(), b'boot')
            self.assertEqual(manifest['inputs']['userdata']['path'], 'esp.img')
            self.assertFalse(CHECK.verify_manifest(output)['flashable'])
            CHECK.verify_sums(output)
            # A coherent checksum list is insufficient if roles were swapped.
            manifest['inputs']['userdata'] = manifest['inputs']['darwin_root']
            (output / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'userdata does not match'):
                CHECK.verify_manifest(output)
            with self.assertRaisesRegex(ValueError, 'userdata to be the ESP'):
                MODULE.build_package(esp, esp_image, kernel, output,
                                     userdata=darwin, darwin_root=darwin)
            manifest['inputs']['userdata'] = manifest['inputs']['esp_image']
            (output / 'manifest.json').write_text(json.dumps(manifest))
            (output / 'esp/EFI/UniXNU/Payloads/kernel.macho').write_bytes(b'wrong kernel')
            with self.assertRaisesRegex(ValueError, 'ESP kernel does not match'):
                CHECK.verify_manifest(output)

    def test_darwin_root_requires_a_real_darwin_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / 'esp'
            payload = esp / 'EFI/UniXNU/Payloads'
            payload.mkdir(parents=True)
            kernel = root / 'kernel.macho'
            kernel.write_bytes(b'kernel')
            (payload / 'kernel.macho').write_bytes(b'kernel')
            esp_image = root / 'esp.img'
            esp_image.write_bytes(b'fat')
            darwin = root / 'darwin.img'
            darwin.write_bytes(b'SHNGROOT' + bytes(4088))
            output = root / 'package'
            manifest = MODULE.build_package(esp, esp_image, kernel, output,
                                             userdata=esp_image, darwin_root=darwin)
            # Stock Polaris has no darwin partition, so the package must say so
            # instead of promising a flash that the bootloader will reject.
            self.assertTrue(any('darwin GPT partition' in b for b in manifest['blockers']))
            script = (output / 'flash.ps1').read_text(encoding='utf-8')
            # The installer probes before it writes anything.
            self.assertIn('partition-size:darwin', script)
            self.assertIn('exit 12', script)
            probe = script.index('partition-size:darwin')
            flash = script.index('flash darwin')
            self.assertLess(probe, flash, 'the partition probe must run before the write')

    def test_package_paths_reject_windows_absolute_and_traversal_forms(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in (r"C:\\Windows\\system32", r"C:relative.txt", r"\\\\server\\share", r"..\\outside.txt"):
                with self.assertRaisesRegex(ValueError, "unsafe package path"):
                    CHECK.safe_member(root, value)

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
            self.assertFalse(manifest["hardware_tested"])
            self.assertFalse(manifest["temporary_boot_tested"])
            self.assertFalse(manifest["userland_tested"])
            self.assertEqual(json.loads((output / "manifest.json").read_text())["flashable"], False)
            self.assertIn("manifest.flashable", (output / "flash.ps1").read_text(encoding="utf-8"))
            self.assertTrue((output / "SHA256SUMS").is_file())
            sums = (output / "SHA256SUMS").read_text(encoding="ascii")
            self.assertIn("README.txt", sums)
            flash_script = (output / "flash.ps1").read_text(encoding="utf-8")
            self.assertIn("SHA-256 package verification passed", flash_script)
            self.assertIn("Manifest flash gates are inconsistent", flash_script)
            self.assertIn("Get-FileHash", flash_script)
            self.assertIn("Unsafe checksum path", flash_script)
            self.assertIn("Manifest has no inputs object", flash_script)
            self.assertIn("Unsafe manifest input path", flash_script)
            self.assertIn("Manifest input SHA-256 mismatch", flash_script)
            self.assertIn("woa_evidence", manifest)
            self.assertTrue(manifest["woa_evidence"]["present"])
            self.assertIn("driver_bundle", manifest)
            verified = CHECK.verify_manifest(output)
            self.assertFalse(verified["flashable"])
            self.assertGreater(CHECK.verify_sums(output), 0)

            (output / "unlisted.bin").write_bytes(b"unlisted")
            with self.assertRaisesRegex(ValueError, "unlisted package files"):
                CHECK.verify_sums(output)
            (output / "unlisted.bin").unlink()
            (output / "esp.img").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                CHECK.verify_sums(output)

            manifest_path = output / "manifest.json"
            original = json.loads(manifest_path.read_text(encoding="utf-8"))
            original["safe_to_flash"] = True
            manifest_path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "safe_to_flash must match flashable"):
                CHECK.verify_manifest(output)
            original["safe_to_flash"] = False
            manifest_path.write_text(json.dumps(original), encoding="utf-8")
            original["flashable"] = True
            original["safe_to_flash"] = True
            original["blockers"] = ["leftover gate"]
            manifest_path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "flashable package still has blockers"):
                CHECK.verify_manifest(output)

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

    def test_firmware_file_carries_adjacent_provenance(self):
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
            firmware = root / "boot-polaris.img"
            firmware.write_bytes(b"firmware")
            (root / "firmware-provenance.json").write_text(json.dumps({
                "board": "xiaomi,polaris", "hardware_tested": False,
            }), encoding="utf-8")
            output = root / "package"
            manifest = MODULE.build_package(esp, esp_image, kernel, output,
                                            firmware=firmware)
            self.assertFalse(manifest["flashable"])
            self.assertEqual(manifest["inputs"]["firmware_provenance"]["path"],
                             "firmware-provenance.json")
            self.assertTrue((output / "firmware-provenance.json").is_file())
            self.assertIn("firmware-provenance.json", (output / "SHA256SUMS").read_text())

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
