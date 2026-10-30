import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PlatformKernelBuildTests(unittest.TestCase):
    def test_polaris_probe_archives_are_force_loaded(self):
        source = (ROOT / "scripts" / "build-platform-kernel.py").read_text(encoding="utf-8")
        self.assertIn("build/polaris-board-probe/libPolarisBoardProbe.a", source)
        self.assertIn("build/polaris-hardware-services/libPolarisHardwareServices.a", source)
        self.assertIn("build/polaris-pmic-input/libPolarisPmicInput.a", source)
        self.assertIn("build/polaris-synaptics-touch/libPolarisSynapticsTouch.a", source)
        self.assertIn("build/polaris-transport-contracts/libPolarisTransportContracts.a", source)
        self.assertIn("build/polaris-a630-probe/libPolarisA630Probe.a", source)
        self.assertIn("build/polaris-runtime/libPolarisRuntime.a", source)
        self.assertIn("build/polaris-pmic-runtime/libPolarisPmicRuntime.a", source)
        self.assertIn("XNU_EXTRA_LD_ARCHIVES", source)
        self.assertIn("-Wl,-force_load,{path}", source)

    def test_archive_configs_are_enabled(self):
        for name in ("polaris_defconfig", "polaris_display_defconfig", "polaris_ipados17_defconfig"):
            config = (ROOT / "configs" / name).read_text(encoding="utf-8")
            self.assertIn("CONFIG_XNU_BUILD_ARCHIVES=y", config)

    def test_prelink_profile_and_final_hash_are_supported(self):
        config = (ROOT / "configs" / "polaris_ipados17_defconfig").read_text(encoding="utf-8")
        self.assertIn("CONFIG_XNU_NATIVE_UFS=y", config)
        source = (ROOT / "scripts" / "build-platform-kernel.py").read_text(encoding="utf-8")
        self.assertIn("final_data = destination.read_bytes()", source)
        self.assertIn("source_kernel_sha256", source)
        self.assertIn("ctx.config.get('XNU_CRYPTO_BOOTSTRAP') == 'prelinked'", source)
        self.assertIn("kernel-prelinked.macho", source)
        self.assertIn("'original_components_prelinked': False", source)
        self.assertIn("'original_components_prelinked': True", source)


if __name__ == "__main__":
    unittest.main()
