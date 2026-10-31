/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Side-effect-free CCI/CSI camera resource contract for Xiaomi Polaris. */
#ifndef POLARIS_CAMERA_POLICY_H
#define POLARIS_CAMERA_POLICY_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum PolarisCameraSensorKind {
    PolarisCameraSensorUnknown = 0,
    PolarisCameraSensorImx363 = 1,
    PolarisCameraSensorOv5675 = 2,
    PolarisCameraSensorS5k3m3 = 3,
};

enum PolarisCameraReason {
    PolarisCameraReasonNone = 0,
    PolarisCameraReasonBoardMismatch = 1,
    PolarisCameraReasonMissingCci = 2,
    PolarisCameraReasonMissingCsi = 3,
    PolarisCameraReasonInvalidSensorAddress = 4,
    PolarisCameraReasonSensorIdentityRequired = 5,
    PolarisCameraReasonFirmwareIncomplete = 6,
    PolarisCameraReasonHardwareValidationRequired = 7,
    /* No camera sensor node was found at all.  This is deliberately distinct
     * from an out-of-range address so an absent DT node is never reported as
     * a bad address.  Appended, so the existing wire values do not move. */
    PolarisCameraReasonMissingSensor = 8,
};

typedef struct {
    uint8_t board_matches;
    uint8_t cci_present;
    uint8_t csiphy_present;
    uint8_t csid_present;
    uint8_t sensor_candidate;
    uint8_t sensor_id_confirmed;
    uint8_t tuning_complete;
    uint8_t sensor_kind;
    uint8_t address7;
} PolarisCameraEvidence;

typedef struct {
    uint8_t resource_contract_valid;
    uint8_t cci_reads_allowed;
    uint8_t sensor_power_allowed;
    uint8_t csi_dma_allowed;
    uint8_t firmware_load_allowed;
    uint32_t reason;
} PolarisCameraPlan;

static inline int polaris_camera_address_valid(uint8_t address7)
{
    return address7 >= 0x03U && address7 <= 0x77U;
}

static inline int polaris_camera_sensor_name_kind(const char *name,
                                                  size_t length,
                                                  uint8_t *kind)
{
    if (name == NULL || kind == NULL || length == 0) return 0;
    struct Candidate { const char *name; uint8_t kind; };
    static const struct Candidate candidates[] = {
        {"imx363", PolarisCameraSensorImx363},
        {"sony,imx363", PolarisCameraSensorImx363},
        {"ov5675", PolarisCameraSensorOv5675},
        {"s5k3m3", PolarisCameraSensorS5k3m3},
    };
    for (size_t i = 0; i < sizeof(candidates) / sizeof(candidates[0]); ++i) {
        size_t expected = 0;
        while (candidates[i].name[expected] != '\0') ++expected;
        if (expected != length) continue;
        size_t j = 0;
        while (j < length && name[j] == candidates[i].name[j]) ++j;
        if (j == length) {
            *kind = candidates[i].kind;
            return 1;
        }
    }
    return 0;
}

static inline PolarisCameraPlan
polaris_camera_make_plan(PolarisCameraEvidence evidence)
{
    PolarisCameraPlan plan = {0, 0, 0, 0, 0, PolarisCameraReasonNone};
    if (!evidence.board_matches) {
        plan.reason = PolarisCameraReasonBoardMismatch;
        return plan;
    }
    if (!evidence.cci_present) {
        plan.reason = PolarisCameraReasonMissingCci;
        return plan;
    }
    if (!evidence.csiphy_present || !evidence.csid_present) {
        plan.reason = PolarisCameraReasonMissingCsi;
        return plan;
    }
    if (!evidence.sensor_candidate) {
        plan.reason = PolarisCameraReasonMissingSensor;
        return plan;
    }
    if (evidence.sensor_kind == PolarisCameraSensorUnknown) {
        /* A node matched the generic camera names but its identity is unknown;
         * nothing in the contract may assume IMX363. */
        plan.reason = PolarisCameraReasonSensorIdentityRequired;
        return plan;
    }
    if (!polaris_camera_address_valid(evidence.address7)) {
        plan.reason = PolarisCameraReasonInvalidSensorAddress;
        return plan;
    }
    if (!evidence.sensor_id_confirmed) {
        plan.reason = PolarisCameraReasonSensorIdentityRequired;
        return plan;
    }
    if (!evidence.tuning_complete) {
        plan.reason = PolarisCameraReasonFirmwareIncomplete;
        return plan;
    }

    /* Resource evidence never authorizes sensor power, CSI DMA or firmware. */
    plan.resource_contract_valid = 1;
    plan.reason = PolarisCameraReasonHardwareValidationRequired;
    return plan;
}

#ifdef __cplusplus
}
#endif

#endif
