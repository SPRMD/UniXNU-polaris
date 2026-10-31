import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PACKAGE = load("make_polaris_package_ios", ROOT / "scripts" / "make-polaris-package.py")
STAGE = load("build_polaris_ios_stage", ROOT / "scripts" / "build-ios-stage.py")
ESP = load("make_polaris_ios_esp", ROOT / "scripts" / "make-ios-esp.py")
INPUTS = load("check_polaris_ios_inputs", ROOT / "scripts" / "check-ios-stage-inputs.py")


class IOSStageScriptTests(unittest.TestCase):
    def test_raw_apfs_uses_object_header_and_checks_container_extent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "root.img"
            raw = bytearray(8192)
            struct.pack_into("<4sIQ", raw, 32, b"NXSB", 4096, 2)
            path.write_bytes(raw)
            self.assertEqual(STAGE.require_raw_apfs(path), {
                "block_size": 4096, "block_count": 2, "container_bytes": 8192,
            })
            path.write_bytes(raw[:4096])
            with self.assertRaisesRegex(SystemExit, "truncated"):
                STAGE.require_raw_apfs(path)

    def test_normalize_raw_apfs_keeps_a_valid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "os.dmg"
            raw = bytearray(8192)
            struct.pack_into("<4sIQ", raw, 32, b"NXSB", 4096, 2)
            path.write_bytes(raw)
            normalized, geometry = STAGE.normalize_apfs_input(path, root / "work")
            self.assertEqual(normalized, path)
            self.assertEqual(geometry["container_bytes"], 8192)

    def test_normalized_apfs_inputs_must_be_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "same.img"
            image.write_bytes(b"same")
            with self.assertRaisesRegex(SystemExit, "different APFS images"):
                STAGE.require_distinct_apfs_images(image, image)
            other = root / "other.img"
            other.write_bytes(b"same")
            with self.assertRaisesRegex(SystemExit, "identical contents"):
                STAGE.require_distinct_apfs_images(image, other)

    def test_source_images_must_be_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os_image = root / "os.dmg"
            system_image = root / "system.dmg"
            os_image.write_bytes(b"os")
            system_image.write_bytes(b"system")
            STAGE.require_distinct_images(os_image, system_image)
            with self.assertRaisesRegex(SystemExit, "different files"):
                STAGE.require_distinct_images(os_image, os_image)
            system_image.write_bytes(b"os")
            with self.assertRaisesRegex(SystemExit, "different content"):
                STAGE.require_distinct_images(os_image, system_image)

    def test_pinned_ios_inputs_are_hashed_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os_image = root / "044-76040-038.dmg"
            system_image = root / "044-76034-038.dmg"
            os_image.write_bytes(b"os")
            system_image.write_bytes(b"system")
            import hashlib
            board = root / "board.toml"
            board.write_text(
                """[board]\nname = 'xiaomi,polaris'\n[ipsw]\nproduct = 'iPad7,1'\nversion = '17.7.11'\nbuild = '21H461'\n[ipsw.sha256]\n\"044-76040-038.dmg\" = '%s'\n\"044-76034-038.dmg\" = '%s'\n""" % (
                    hashlib.sha256(b"os").hexdigest(),
                    hashlib.sha256(b"system").hexdigest(),
                ),
                encoding="utf-8",
            )
            report = INPUTS.verify(root, board)
            self.assertTrue(report["verified"])
            self.assertEqual(report["members"]["044-76040-038.dmg"]["bytes"], 2)

    def test_misplaced_magic_and_invalid_geometry_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "root.img"
            path.write_bytes(b"NXSB" + bytes(8192))
            with self.assertRaisesRegex(SystemExit, "byte 32"):
                STAGE.require_raw_apfs(path)
            for block_size, count in ((0, 2), (6144, 2), (4096, 0), (131072, 1)):
                raw = bytearray(8192)
                struct.pack_into("<4sIQ", raw, 32, b"NXSB", block_size, count)
                path.write_bytes(raw)
                with self.assertRaisesRegex(SystemExit, "geometry"):
                    STAGE.require_raw_apfs(path)

    def test_ios_stage_entrypoints_are_host_only_and_guarded(self):
        source = (ROOT / "scripts" / "build-ios-stage.py").read_text(encoding="utf-8")
        self.assertIn("flashable", source)
        self.assertIn("no phone access", source)
        self.assertIn("make-trust-bundle.py", source)
        self.assertIn("make-ios-esp.py", source)
        self.assertIn("make-userdata-linux.py", source)
        self.assertIn("--driver-bundle", source)
        self.assertIn("driver bundle not found", source)
        self.assertIn("paths.append(args.driver_bundle)", source)

    def test_ipados_stage_requests_experimental_input_services(self):
        builder = (ROOT / "scripts" / "build-ios-stage.py").read_text(encoding="utf-8")
        esp = (ROOT / "scripts" / "make-ios-esp.py").read_text(encoding="utf-8")
        self.assertIn('"--ipados-stage"', builder)
        self.assertIn("polaris-touch-hid=1", esp)
        self.assertIn("polariskeys=1", esp)
        self.assertIn("polarisbattery=1", esp)
        self.assertIn("def render_toml(ipados_stage: bool)", esp)
        self.assertNotIn("polaris-touch-hid=1", ESP.render_toml(False))
        self.assertIn("polaris-touch-hid=1", ESP.render_toml(True))
        self.assertIn("polariskeys=1", ESP.render_toml(True))
        self.assertIn("polarisbattery=1", ESP.render_toml(True))
        self.assertIn("'boot_profile'", esp)
        self.assertIn("'experimental_input_services'", esp)

    def test_optional_driver_bundle_is_validated_and_forwarded(self):
        source = (ROOT / "scripts" / "build-ios-stage.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--driver-bundle"', source)
        self.assertIn("driver bundle not found", source)
        self.assertIn('package_args.extend(["--driver-bundle", str(args.driver_bundle)])', source)

    def test_input_hash_report_is_validated_and_carried(self):
        source = (ROOT / "scripts" / "build-ios-stage.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--input-hash-report"', source)
        self.assertIn("input hash report is not marked verified", source)
        self.assertIn('shutil.copy2(args.input_hash_report, out / "ios-input-hashes.json")', source)
        self.assertIn("rewrite_package_sums(package)", source)

    def test_os_and_system_os_must_be_distinct(self):
        source = (ROOT / "scripts" / "build-ios-stage.py").read_text(encoding="utf-8")
        self.assertIn("require_distinct_images(args.os, args.system_os)", source)
        self.assertIn("OS and SystemOS inputs must be different files", source)

    def test_udif_extractor_treats_liblzfse_as_lazy_dependency(self):
        source = (ROOT / "scripts" / "udif-extract.py").read_text(encoding="utf-8")
        self.assertIn("except ImportError", source)
        self.assertIn("requires the Python liblzfse module", source)

    def test_package_carries_optional_darwin_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / "esp"
            esp.mkdir()
            (esp / "BOOTAA64.EFI").write_bytes(b"efi")
            esp_image = root / "esp.img"
            esp_image.write_bytes(b"esp")
            kernel = root / "kernel.macho"
            kernel.write_bytes(b"kernel")
            kernel.with_suffix(".json").write_text(json.dumps({
                "kernel_sha256": PACKAGE.sha256(kernel),
                "final_configured_link_passed": True,
                "original_components_prelinked": True,
            }), encoding="utf-8")
            darwin = root / "darwin-root.img"
            darwin.write_bytes(b"root")
            output = root / "package"
            manifest = PACKAGE.build_package(esp, esp_image, kernel, output,
                                             darwin_root=darwin)
            self.assertFalse(manifest["flashable"])
            self.assertEqual(manifest["inputs"]["darwin_root"]["path"], "darwin-root.img")
            self.assertTrue((output / "darwin-root.img").is_file())
            self.assertIn("darwin", (output / "flash.ps1").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
