import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PlatformKernelBuildTests(unittest.TestCase):
    def test_polaris_probe_archives_are_force_loaded(self):
        source = (ROOT / "scripts" / "build-platform-kernel.py").read_text(encoding="utf-8")
        self.assertIn("build/polaris-board-probe/libPolarisBoardProbe.a", source)
        self.assertIn("build/polaris-hardware-services/libPolarisHardwareServices.a", source)
        self.assertIn("XNU_EXTRA_LD_ARCHIVES", source)
        self.assertIn("-Wl,-force_load,{path}", source)

    def test_archive_configs_are_enabled(self):
        for name in ("polaris_defconfig", "polaris_display_defconfig"):
            config = (ROOT / "configs" / name).read_text(encoding="utf-8")
            self.assertIn("CONFIG_XNU_BUILD_ARCHIVES=y", config)


if __name__ == "__main__":
    unittest.main()
