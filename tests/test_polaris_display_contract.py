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
            "PolarisDisplayPanelReasonHardwareValidationRequired",
            "PolarisDisplayPanelReasonBoardMismatch",
            "PolarisDisplayPanelReasonNoPanelCandidate",
            "PolarisDisplayPanelReasonGeometryUnconfirmed",
            "PolarisDisplayPanelReasonPanelIdentityRequired",
            "dsi_writes_allowed",
            "backlight_allowed",
        ):
            self.assertIn(value, header)

    def test_service_is_board_gated_and_has_no_hardware_io(self):
        source = (DRIVER / "PolarisDisplayContract.cpp").read_text(encoding="utf-8")
        self.assertIn('PE_parse_boot_argn("polaris-display-probe"', source)
        self.assertIn('compatibleContains(root, "xiaomi,polaris")', source)
        self.assertIn('compatibleContains(root, "qcom,sdm845")', source)
        self.assertIn('"polaris-display-dsi-writes-allowed"', source)
        self.assertIn('"polaris-display-backlight-allowed"', source)
        self.assertIn('"polaris-display-darwin-driver-ready", false', source)
        for forbidden in (
            "ml_io_map", "IODeviceMemory", "IOMemoryDescriptor", "write32",
            "write8", "registerInterrupt", "IOInterruptEventSource",
            "setPowerState", "loadFirmware",
        ):
            self.assertNotIn(forbidden, source)

    def test_service_uses_the_fail_closed_plan_instead_of_a_fixed_resolution(self):
        """The contract may not publish a resolution it never read from the DT.

        The reference Polaris DTB timing nodes disagree on height (1080x1920 for
        the JDI R63452 build, 1080x2160 for JDI NT35596S and EBBG FT8716,
        1080x2246 for EBBG FT8719), so a single "1080x2160" claim was an
        overstatement.
        """
        source = (DRIVER / "PolarisDisplayContract.cpp").read_text(encoding="utf-8")
        self.assertIn("#include \"PolarisDisplayPanelProtocol.h\"", source)
        self.assertIn("polaris_display_panel_make_plan(evidence)", source)
        self.assertIn('"polaris-display-plan-reason", plan.reason, 32', source)
        self.assertIn('"polaris-display-resource-contract-valid"', source)
        self.assertIn('"polaris-display-panel-selected", false', source)
        self.assertIn('"polaris-display-geometry-confirmed", false', source)
        self.assertIn('"polaris-display-resolution", "unresolved"', source)
        self.assertIn('"polaris-display-resolution-candidates"', source)
        self.assertIn('"polaris-display-dsi-lanes-confirmed", false', source)
        # A measured-looking resolution or lane count may not be published.
        self.assertNotIn('"polaris-display-resolution", "1080x2160"', source)
        self.assertNotIn('"polaris-display-dsi-lanes", 4U, 32', source)
        # The service must derive the panel kind from the DT label instead of
        # hardcoding one panel.
        self.assertIn("getProperty(\"label\")", source)
        self.assertIn("polaris_display_panel_name_kind", source)

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
