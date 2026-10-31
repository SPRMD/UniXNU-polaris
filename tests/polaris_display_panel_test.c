#include <assert.h>
#include "../drivers/PolarisDisplayContract/PolarisDisplayPanelProtocol.h"

int main(void)
{
    uint8_t kind = 0;
    const char *panel = "dsi_jdi_fhd_nt35596s_video_display";
    assert(polaris_display_panel_name_kind(
        panel, sizeof("dsi_jdi_fhd_nt35596s_video_display") - 1, &kind));
    assert(kind == PolarisDisplayPanelJdiNt35596sVideo);
    assert(!polaris_display_panel_name_kind("dsi_unknown", 11, &kind));

    PolarisDisplayPanelEvidence evidence = {1, 1, 1, kind, 1080, 2160, 4, 0};
    PolarisDisplayPanelPlan plan = polaris_display_panel_make_plan(evidence);
    assert(plan.resource_contract_valid == 1);
    assert(plan.reason == PolarisDisplayPanelReasonHardwareValidationRequired);
    assert(plan.dsi_writes_allowed == 0);
    assert(plan.backlight_allowed == 0);
    assert(plan.gpu_composition_allowed == 0);

    evidence.active_panel_selected = 0;
    plan = polaris_display_panel_make_plan(evidence);
    assert(plan.reason == PolarisDisplayPanelReasonPanelNotSelected);
    evidence.active_panel_selected = 1;
    evidence.width = 1440;
    plan = polaris_display_panel_make_plan(evidence);
    assert(plan.reason == PolarisDisplayPanelReasonInvalidGeometry);
    return 0;
}
