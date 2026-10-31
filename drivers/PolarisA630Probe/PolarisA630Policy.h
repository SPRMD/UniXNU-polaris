/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef POLARIS_A630_POLICY_H
#define POLARIS_A630_POLICY_H

/*
 * Portable, side-effect-free policy for the Polaris A630 bring-up.
 *
 * The Darwin probe can use this header to decide whether the DT evidence is
 * internally consistent.  It deliberately never authorizes MMIO, firmware
 * loading, DMA, SMMU programming, or a rendering user client.  Those actions
 * require an independently recorded temporary boot on a real Polaris.
 */

#include <stdint.h>

#include "PolarisA630Board.h"

#ifdef __cplusplus
extern "C" {
#endif

enum PolarisA630Reason {
    PolarisA630ReasonNone = 0,
    PolarisA630ReasonBoardMismatch = 1,
    PolarisA630ReasonMissingResource = 2,
    PolarisA630ReasonInvalidResource = 3,
    PolarisA630ReasonUnsupportedChip = 4,
    PolarisA630ReasonFirmwareIncomplete = 5,
    PolarisA630ReasonHardwareValidationRequired = 6,
};

/* The local unixnu-adreno6xx reference targets SM7325/A642L.  Its chip ID is
 * retained here solely as a negative-test sentinel so an A642L board port
 * cannot be mistaken for Polaris SDM845/A630.  It is deliberately absent from
 * polaris_a630_chip_id_supported(). */
enum {
    POLARIS_A630_REFERENCE_ONLY_A642L_CHIP_ID = 0x06030500u,
};

typedef struct {
    uint64_t address;
    uint64_t size;
} PolarisA630Range;

typedef struct {
    uint8_t board_matches;
    uint8_t gpu_present;
    uint8_t gmu_present;
    uint8_t smmu_present;
    uint8_t chip_id_confirmed;
    uint8_t firmware_complete;
    uint32_t chip_id;
    PolarisA630Range gpu;
    PolarisA630Range gmu;
    PolarisA630Range smmu;
} PolarisA630Evidence;

typedef struct {
    uint8_t resource_contract_valid;
    uint8_t hardware_writes_allowed;
    uint8_t firmware_load_allowed;
    uint8_t dma_allowed;
    uint32_t reason;
} PolarisA630Plan;

static inline int polaris_a630_range_valid(PolarisA630Range range)
{
    return range.size != 0 && range.address + range.size > range.address;
}

static inline int polaris_a630_chip_id_supported(uint32_t chip_id)
{
    return chip_id == POLARIS_A630_CHIP_ID_REV0 ||
           chip_id == POLARIS_A630_CHIP_ID_REV1;
}

static inline PolarisA630Plan polaris_a630_make_plan(PolarisA630Evidence evidence)
{
    PolarisA630Plan plan = {0, 0, 0, 0, PolarisA630ReasonNone};
    if (!evidence.board_matches) {
        plan.reason = PolarisA630ReasonBoardMismatch;
        return plan;
    }
    if (!evidence.gpu_present || !evidence.gmu_present || !evidence.smmu_present) {
        plan.reason = PolarisA630ReasonMissingResource;
        return plan;
    }
    if (!polaris_a630_range_valid(evidence.gpu) ||
        !polaris_a630_range_valid(evidence.gmu) ||
        !polaris_a630_range_valid(evidence.smmu)) {
        plan.reason = PolarisA630ReasonInvalidResource;
        return plan;
    }
    if (!evidence.chip_id_confirmed ||
        !polaris_a630_chip_id_supported(evidence.chip_id)) {
        plan.reason = PolarisA630ReasonUnsupportedChip;
        return plan;
    }
    if (!evidence.firmware_complete) {
        plan.reason = PolarisA630ReasonFirmwareIncomplete;
        return plan;
    }

    /* Resource evidence is sufficient for a contract, never for MMIO. */
    plan.resource_contract_valid = 1;
    plan.reason = PolarisA630ReasonHardwareValidationRequired;
    return plan;
}

#ifdef __cplusplus
}
#endif

#endif
