import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "drivers" / "PolarisDisplayContract"


class PolarisDisplayContractTests(unittest.TestCase):
    def test_protocol_carries_known_panel_candidates_and_fail_closed_plan(self):
        header = (DRIVER / "PolarisDisplayPanelProtocol.h").read_text(encoding="utf-8")
        for value in (
            "dsi_jdi_fhd_nt35596s_video_display",
            "dsi_jdi_fhd_r63452_cmd_display",
            "dsi_ebbg_fhd_ft8716_video_display",
            "dsi_ebbg_fhd_ft8719_video_display",
            "1080",
            "2160",
            "PolarisDisplayPanelReasonHardwareValidationRequired",
            "dsi_writes_allowed",
            "backlight_allowed",
        ):
            self.assertIn(value, header)

    def test_service_is_board_gated_and_has_no_hardware_io(self):
        source = (DRIVER / "PolarisDisplayContract.cpp").read_text(encoding="utf-8")
        self.assertIn('PE_parse_boot_argn("polaris-display-probe"', source)
        self.assertIn('compatibleContains(root, "xiaomi,polaris")', source)
        self.assertIn('compatibleContains(root, "qcom,sdm845")', source)
        self.assertIn('"polaris-display-dsi-writes-allowed", false', source)
        self.assertIn('"polaris-display-backlight-allowed", false', source)
        self.assertIn('"polaris-display-darwin-driver-ready", false', source)
        for forbidden in (
            "ml_io_map", "IODeviceMemory", "IOMemoryDescriptor", "write32",
            "write8", "registerInterrupt", "IOInterruptEventSource",
            "setPowerState", "loadFirmware",
        ):
            self.assertNotIn(forbidden, source)

    def test_archive_is_wired_into_darwin_build(self):
        board = (ROOT / "board.toml").read_text(encoding="utf-8")
        builder = (ROOT / "scripts" / "build-arm-driver.py").read_text(encoding="utf-8")
        linker = (ROOT / "scripts" / "build-platform-kernel.py").read_text(encoding="utf-8")
        runtime = (ROOT / "drivers" / "PolarisRuntime" / "PolarisRuntime.cpp").read_text(encoding="utf-8")
        self.assertIn("build-arm-driver.py PolarisDisplayContract", board)
        self.assertIn("'PolarisDisplayContract'", builder)
        self.assertIn("libPolarisDisplayContract.a", linker)
        self.assertIn("polaris_display_contract_static_init", runtime)
        self.assertIn('"PolarisDisplayContract"', runtime)
        self.assertIn('polaris-display-probe', runtime)


if __name__ == "__main__":
    unittest.main()
