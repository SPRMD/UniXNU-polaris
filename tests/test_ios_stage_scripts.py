import importlib.util
import json
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


class IOSStageScriptTests(unittest.TestCase):
    def test_ios_stage_entrypoints_are_host_only_and_guarded(self):
        source = (ROOT / "scripts" / "build-ios-stage.py").read_text(encoding="utf-8")
        self.assertIn("flashable", source)
        self.assertIn("no phone access", source)
        self.assertIn("make-trust-bundle.py", source)
        self.assertIn("make-ios-esp.py", source)
        self.assertIn("make-userdata-linux.py", source)

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
