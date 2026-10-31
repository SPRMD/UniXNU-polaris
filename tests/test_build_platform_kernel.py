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
        self.assertIn("build/polaris-peripheral-contracts/libPolarisPeripheralContracts.a", source)
        self.assertIn("build/polaris-nfc-contract/libPolarisNfcContract.a", source)
        self.assertIn("build/polaris-camera-contract/libPolarisCameraContract.a", source)
        self.assertIn("build/polaris-a630-probe/libPolarisA630Probe.a", source)
        self.assertIn("build/polaris-display-contract/libPolarisDisplayContract.a", source)
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

    def test_ios_stage_workflow_selects_prelinked_kernel(self):
        workflow = (ROOT / ".github" / "workflows" / "polaris-build.yml").read_text(encoding="utf-8")
        marker = "- name: Normalize build artifacts"
        self.assertIn(marker, workflow)
        stage = workflow.split(marker, 1)[1].split("- name:", 1)[0]
        self.assertIn("-name kernel-prelinked.macho", stage)
        self.assertNotIn("-name kernel.macho", stage)
        package_marker = "- name: Assemble guarded iPadOS stage package"
        self.assertIn(package_marker, workflow)
        package = workflow.split(package_marker, 1)[1].split("- name:", 1)[0]
        self.assertIn("--os out/ios-inputs/044-76040-038.dmg", package)
        self.assertIn("--system-os out/ios-inputs/044-76034-038.dmg", package)
        self.assertNotIn("--system-os out/ios-inputs/044-76040-038.dmg", package)
        self.assertIn("scripts/check-ios-stage-inputs.py", workflow)
        self.assertIn("--output out/ios-inputs/ipsw-inputs.json", workflow)
        self.assertIn("name: host-reports", workflow)
        self.assertIn("--driver-bundle out/host/polaris-driver-bundle", workflow)
        self.assertIn("scripts/check-ios-stage-inputs.py", workflow)
        self.assertIn("--input-hash-report out/ios-inputs/ios-input-hashes.json", workflow)
        self.assertGreaterEqual(workflow.count("sha256sum -c SHA256SUMS"), 2)
        self.assertGreaterEqual(workflow.count("name: host-reports"), 2)
        self.assertGreaterEqual(workflow.count("--driver-bundle out/host/polaris-driver-bundle"), 2)

    def test_platform_package_workflow_selects_source_kernel(self):
        workflow = (ROOT / ".github" / "workflows" / "polaris-build.yml").read_text(encoding="utf-8")
        marker = "- name: Validate kernel and assemble ESP directory"
        self.assertIn(marker, workflow)
        package = workflow.split(marker, 1)[1].split("- name:", 1)[0]
        self.assertIn("-name kernel.macho", package)
        self.assertNotIn("-name kernel-prelinked.macho", package)


if __name__ == "__main__":
    unittest.main()
