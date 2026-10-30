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
