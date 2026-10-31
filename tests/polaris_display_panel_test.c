#include <assert.h>
#include "../drivers/PolarisDisplayContract/PolarisDisplayPanelProtocol.h"

/* Every panel name in the contract must round-trip to its own kind, and no
 * other string may be silently accepted. */
static void check_name_kind(void)
{
    static const char *const names[] = {
        "dsi_jdi_fhd_nt35596s_video_display",
        "dsi_jdi_fhd_r63452_cmd_display",
        "dsi_ebbg_fhd_ft8716_video_display",
        "dsi_ebbg_fhd_ft8719_video_display",
    };
    static const uint8_t kinds[] = {
        PolarisDisplayPanelJdiNt35596sVideo,
        PolarisDisplayPanelJdiR63452Cmd,
        PolarisDisplayPanelEbbgFt8716Video,
        PolarisDisplayPanelEbbgFt8719Video,
    };
    for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
        uint8_t kind = PolarisDisplayPanelUnknown;
        size_t length = 0;
        while (names[i][length] != '\0') ++length;
        assert(polaris_display_panel_name_kind(names[i], length, &kind));
        assert(kind == kinds[i]);
        /* A truncated or padded name must not match. */
        assert(!polaris_display_panel_name_kind(names[i], length - 1, &kind));
        assert(!polaris_display_panel_name_kind(names[i], length + 1, &kind));
    }

    uint8_t kind = 0xff;
    /* A near-miss must not match, and must not write to the output. */
    assert(!polaris_display_panel_name_kind("dsi_jdi_fhd_nt35596s_video_displa",
                                            33, &kind));
    assert(kind == 0xff);
    assert(!polaris_display_panel_name_kind("dsi_unknown", 11, &kind));
    assert(!polaris_display_panel_name_kind("", 0, &kind));
    assert(!polaris_display_panel_name_kind(NULL, 11, &kind));
    assert(!polaris_display_panel_name_kind("dsi_unknown", 11, NULL));
}

/* An absent or malformed DT must fail closed with the specific reason and
 * never publish capability flags or a valid contract. */
static void check_fail_closed_reasons(void)
{
    const uint8_t known = PolarisDisplayPanelJdiNt35596sVideo;
    PolarisDisplayPanelPlan plan;

    PolarisDisplayPanelEvidence complete = {1, 1, 1, known, 1080, 2160, 4, 0};
    plan = polaris_display_panel_make_plan(complete);
    assert(plan.resource_contract_valid == 1);
    assert(plan.reason == PolarisDisplayPanelReasonHardwareValidationRequired);
    assert(plan.dsi_writes_allowed == 0);
    assert(plan.backlight_allowed == 0);
    assert(plan.gpu_composition_allowed == 0);

    /* Board node missing / not a Polaris. */
    PolarisDisplayPanelEvidence evidence = complete;
    evidence.board_matches = 0;
    plan = polaris_display_panel_make_plan(evidence);
    assert(plan.reason == PolarisDisplayPanelReasonBoardMismatch);
    assert(plan.resource_contract_valid == 0);

    /* No dsi-display node at all in the DT. */
    evidence = complete;
    evidence.candidate_present = 0;
    plan = polaris_display_panel_make_plan(evidence);
    assert(plan.reason == PolarisDisplayPanelReasonNoPanelCandidate);
    assert(plan.resource_contract_valid == 0);

    /* The DT does not identify a single panel: either no label matched a known
     * build, or several distinct candidate builds are present. */
    evidence = complete;
    evidence.panel_kind = PolarisDisplayPanelUnknown;
    plan = polaris_display_panel_make_plan(evidence);
    assert(plan.reason == PolarisDisplayPanelReasonPanelIdentityRequired);
    assert(plan.resource_contract_valid == 0);

    /* Timing nodes were not parsed: geometry is unconfirmed, not wrong. */
    evidence = complete;
    evidence.width = 0;
    evidence.height = 0;
    evidence.lanes = 0;
    plan = polaris_display_panel_make_plan(evidence);
    assert(plan.reason == PolarisDisplayPanelReasonGeometryUnconfirmed);
    assert(plan.resource_contract_valid == 0);

    /* Real Polaris candidates disagree on height, so a different panel height
     * must be rejected as a contradiction rather than accepted. */
    evidence = complete;
    evidence.height = 1920;
    plan = polaris_display_panel_make_plan(evidence);
    assert(plan.reason == PolarisDisplayPanelReasonInvalidGeometry);
    evidence = complete;
    evidence.height = 2246;
    plan = polaris_display_panel_make_plan(evidence);
    assert(plan.reason == PolarisDisplayPanelReasonInvalidGeometry);
    evidence = complete;
    evidence.width = 1440;
    plan = polaris_display_panel_make_plan(evidence);
    assert(plan.reason == PolarisDisplayPanelReasonInvalidGeometry);
    evidence = complete;
    evidence.lanes = 2;
    plan = polaris_display_panel_make_plan(evidence);
    assert(plan.reason == PolarisDisplayPanelReasonInvalidGeometry);

    /* Panel never selected. */
    evidence = complete;
    evidence.active_panel_selected = 0;
    plan = polaris_display_panel_make_plan(evidence);
    assert(plan.reason == PolarisDisplayPanelReasonPanelNotSelected);
    assert(plan.resource_contract_valid == 0);
    assert(plan.dsi_writes_allowed == 0);
    assert(plan.backlight_allowed == 0);
}

int main(void)
{
    check_name_kind();
    check_fail_closed_reasons();
    return 0;
}
