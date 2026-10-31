import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "drivers" / "PolarisHidInput"


class PolarisHidInputSourceTests(unittest.TestCase):
    def test_abi_record_is_pinned_to_stage(self):
        abi = json.loads((ROOT / "scripts" / "data" / "hid-device-abi.json").read_text(encoding="utf-8"))
        self.assertEqual(abi["instance_bytes"], 208)
        self.assertEqual(len(abi["methods"]), 207)
        self.assertIn("21H461", abi["description"])
        self.assertTrue((DRIVER / "OriginalHidDeviceABI.h").is_file())

    def test_hid_bridge_uses_only_polaris_sources_and_explicit_gate(self):
        source = (DRIVER / "PolarisHidInput.cpp").read_text(encoding="utf-8")
        probe = (DRIVER / "PolarisHidProbe.cpp").read_text(encoding="utf-8")
        for text in (source, probe):
            self.assertIn("PolarisHidInput", text)
            self.assertIn("polaris-touch-hid", text)
            self.assertNotIn("NativeHidInput", text)
            self.assertNotIn("ShengHidInput", text)
        self.assertIn("polaris_touch_runtime_set_sink", source)
        self.assertIn("polaris_buttons_set_sink", source)
        self.assertIn("polaris_hid_device_size != 208", probe)
        self.assertIn("polaris_hid_touch_start", probe)
        self.assertIn('extern "C" kmod_info_t g_kernel_kmod_info', probe)

    def test_hid_is_only_selected_for_ipados_stage(self):
        config = (ROOT / "configs" / "polaris_ipados17_defconfig").read_text(encoding="utf-8")
        builder = (ROOT / "scripts" / "build-platform-kernel.py").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "polaris-build.yml").read_text(encoding="utf-8")
        self.assertIn("CONFIG_XNU_POLARIS_HID_INPUT=y", config)
        self.assertIn("XNU_POLARIS_HID_INPUT", builder)
        self.assertIn("build/polaris-hid-input/", workflow)
        self.assertIn("flashable=false", (DRIVER / "README.md").read_text(encoding="utf-8"))

    def test_hid_recipe_tracks_the_pinned_prelink_kit_name(self):
        # The kit directory name belongs to the pinned upstream tree, which
        # renamed kits/XnuPrelink to kits/NativePrelink. CI run #26 failed with
        # ModuleNotFoundError because the recipe still hardcoded the old name.
        board = (ROOT / "board.toml").read_text(encoding="utf-8")
        pinned = re.search(r'tool = "(kits/[^"]+)/emit_prelink\.py"', board)
        self.assertIsNotNone(pinned, "board.toml must name the pinned prelink kit")
        kit = pinned.group(1)
        builder = (ROOT / "scripts" / "build-platform-kernel.py").read_text(encoding="utf-8")
        recipe = (ROOT / "scripts" / "build-polaris-hid-input.py").read_text(encoding="utf-8")
        self.assertIn(f"'{kit}'", builder)
        self.assertIn(f"'{kit}'", recipe)
        self.assertNotIn("sys.path.insert(0, str(BUILD_ROOT / 'kits/", recipe)

    def test_hid_recipe_resolves_the_kit_by_content(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory) / "tree"
            kit = tree / "kits" / "NativePrelink"
            kit.mkdir(parents=True)
            (kit / "native_prelink.py").write_text(
                "def macho(data, at=0):\n    raise RuntimeError('stub kit')\n", encoding="utf-8")
            found = subprocess.run(
                [sys.executable, "-B", str(ROOT / "scripts" / "build-polaris-hid-input.py"),
                 "--build-root", str(tree)],
                capture_output=True, text=True, timeout=180)
            self.assertNotIn("No module named", found.stderr)
            self.assertNotIn("no native_prelink kit", found.stderr)

            empty = Path(directory) / "empty"
            empty.mkdir()
            missing = subprocess.run(
                [sys.executable, "-B", str(ROOT / "scripts" / "build-polaris-hid-input.py"),
                 "--build-root", str(empty)],
                capture_output=True, text=True, timeout=180)
            self.assertNotEqual(missing.returncode, 0)
            # Both candidate directories are named, so a future upstream rename
            # is diagnosable from the failure alone.
            self.assertIn("NativePrelink", missing.stderr)
            self.assertIn("XnuPrelink", missing.stderr)

    def test_touch_axes_are_polaris_dimensions(self):
        source = (DRIVER / "PolarisHidInput.cpp").read_text(encoding="utf-8")
        self.assertIn("transformCoordinate(xs[i],1080)", source)
        self.assertIn("transformCoordinate(ys[i],2160)", source)


if __name__ == "__main__":
    unittest.main()
