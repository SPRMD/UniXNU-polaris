/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Portable, side-effect-free display panel contract for Xiaomi Polaris. */
#ifndef POLARIS_DISPLAY_PANEL_PROTOCOL_H
#define POLARIS_DISPLAY_PANEL_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum PolarisDisplayPanelKind {
    PolarisDisplayPanelUnknown = 0,
    PolarisDisplayPanelJdiNt35596sVideo = 1,
    PolarisDisplayPanelJdiR63452Cmd = 2,
    PolarisDisplayPanelEbbgFt8716Video = 3,
    PolarisDisplayPanelEbbgFt8719Video = 4,
};

enum PolarisDisplayPanelReason {
    PolarisDisplayPanelReasonNone = 0,
    PolarisDisplayPanelReasonBoardMismatch = 1,
    PolarisDisplayPanelReasonNoPanelCandidate = 2,
    PolarisDisplayPanelReasonInvalidGeometry = 3,
    PolarisDisplayPanelReasonPanelNotSelected = 4,
    PolarisDisplayPanelReasonHardwareValidationRequired = 5,
    /* A panel candidate exists but no timing geometry was read from the DT.
     * Deliberately distinct from InvalidGeometry so "not parsed yet" is never
     * reported as "contradictory".  Appended, so existing values do not move. */
    PolarisDisplayPanelReasonGeometryUnconfirmed = 6,
    /* The DT does not identify one panel: either no dsi-display label matched a
     * known panel build, or several distinct panel builds are present and
     * nothing says which one is fitted. */
    PolarisDisplayPanelReasonPanelIdentityRequired = 7,
};

typedef struct {
    uint8_t board_matches;
    uint8_t candidate_present;
    uint8_t active_panel_selected;
    uint8_t panel_kind;
    uint16_t width;
    uint16_t height;
    uint8_t lanes;
    uint8_t command_mode;
} PolarisDisplayPanelEvidence;

typedef struct {
    uint8_t resource_contract_valid;
    uint8_t dsi_writes_allowed;
    uint8_t backlight_allowed;
    uint8_t gpu_composition_allowed;
    uint32_t reason;
} PolarisDisplayPanelPlan;

static inline int polaris_display_panel_name_kind(const char *name,
                                                  size_t length,
                                                  uint8_t *kind)
{
    if (name == NULL || kind == NULL || length == 0) return 0;
    struct Candidate { const char *name; uint8_t kind; };
    static const struct Candidate candidates[] = {
        {"dsi_jdi_fhd_nt35596s_video_display", PolarisDisplayPanelJdiNt35596sVideo},
        {"dsi_jdi_fhd_r63452_cmd_display", PolarisDisplayPanelJdiR63452Cmd},
        {"dsi_ebbg_fhd_ft8716_video_display", PolarisDisplayPanelEbbgFt8716Video},
        {"dsi_ebbg_fhd_ft8719_video_display", PolarisDisplayPanelEbbgFt8719Video},
    };
    for (size_t i = 0; i < sizeof(candidates) / sizeof(candidates[0]); ++i) {
        size_t expected = 0;
        while (candidates[i].name[expected] != '\0') ++expected;
        if (expected == length) {
            size_t j = 0;
            while (j < length && name[j] == candidates[i].name[j]) ++j;
            if (j == length) {
                *kind = candidates[i].kind;
                return 1;
            }
        }
    }
    return 0;
}

static inline PolarisDisplayPanelPlan
polaris_display_panel_make_plan(PolarisDisplayPanelEvidence evidence)
{
    PolarisDisplayPanelPlan plan = {0, 0, 0, 0, PolarisDisplayPanelReasonNone};
    if (!evidence.board_matches) {
        plan.reason = PolarisDisplayPanelReasonBoardMismatch;
        return plan;
    }
    if (!evidence.candidate_present) {
        plan.reason = PolarisDisplayPanelReasonNoPanelCandidate;
        return plan;
    }
    if (evidence.panel_kind == PolarisDisplayPanelUnknown) {
        plan.reason = PolarisDisplayPanelReasonPanelIdentityRequired;
        return plan;
    }
    if (evidence.width == 0 || evidence.height == 0 || evidence.lanes == 0) {
        /* Nothing about the panel timing has been read from the DT, so the
         * contract may not assert 1080x2160/4-lane geometry yet. */
        plan.reason = PolarisDisplayPanelReasonGeometryUnconfirmed;
        return plan;
    }
    if (evidence.width != 1080 || evidence.height != 2160 ||
        evidence.lanes != 4) {
        plan.reason = PolarisDisplayPanelReasonInvalidGeometry;
        return plan;
    }
    if (!evidence.active_panel_selected) {
        plan.reason = PolarisDisplayPanelReasonPanelNotSelected;
        return plan;
    }
    /* A valid DT contract never authorizes DSI writes or backlight control. */
    plan.resource_contract_valid = 1;
    plan.reason = PolarisDisplayPanelReasonHardwareValidationRequired;
    return plan;
}

#ifdef __cplusplus
}
#endif

#endif
