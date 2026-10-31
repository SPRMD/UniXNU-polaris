/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <stdio.h>
#include <stdint.h>
#include "../drivers/PolarisA630Probe/PolarisA630Policy.h"

static unsigned checks;
#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "CHECK failed at %s:%d: %s\n", __FILE__, __LINE__, #condition); \
        return 1; \
    } \
    ++checks; \
} while (0)

static PolarisA630Evidence complete_evidence(void)
{
    PolarisA630Evidence evidence = {0};
    evidence.board_matches = 1;
    evidence.gpu_present = 1;
    evidence.gmu_present = 1;
    evidence.smmu_present = 1;
    evidence.chip_id_confirmed = 1;
    evidence.firmware_complete = 1;
    evidence.chip_id = 0x06030000u;
    evidence.gpu = (PolarisA630Range){0x05000000u, 0x01000000u};
    evidence.gmu = (PolarisA630Range){0x05040000u, 0x00100000u};
    evidence.smmu = (PolarisA630Range){0x05080000u, 0x00100000u};
    return evidence;
}

int main(void)
{
    PolarisA630Evidence evidence = complete_evidence();
    PolarisA630Plan plan = polaris_a630_make_plan(evidence);
    CHECK(plan.resource_contract_valid == 1);
    CHECK(plan.hardware_writes_allowed == 0);
    CHECK(plan.firmware_load_allowed == 0);
    CHECK(plan.dma_allowed == 0);
    CHECK(plan.reason == PolarisA630ReasonHardwareValidationRequired);

    evidence.board_matches = 0;
    plan = polaris_a630_make_plan(evidence);
    CHECK(plan.resource_contract_valid == 0);
    CHECK(plan.reason == PolarisA630ReasonBoardMismatch);
    evidence = complete_evidence();

    evidence.gmu_present = 0;
    plan = polaris_a630_make_plan(evidence);
    CHECK(plan.reason == PolarisA630ReasonMissingResource);
    evidence = complete_evidence();

    evidence.gpu.size = 0;
    plan = polaris_a630_make_plan(evidence);
    CHECK(plan.reason == PolarisA630ReasonInvalidResource);
    evidence = complete_evidence();

    /* A642L/SM7325 from references/unixnu-adreno6xx is not Polaris A630. */
    evidence.chip_id = POLARIS_A630_REFERENCE_ONLY_A642L_CHIP_ID;
    plan = polaris_a630_make_plan(evidence);
    CHECK(plan.reason == PolarisA630ReasonUnsupportedChip);
    evidence = complete_evidence();

    evidence.firmware_complete = 0;
    plan = polaris_a630_make_plan(evidence);
    CHECK(plan.reason == PolarisA630ReasonFirmwareIncomplete);

    evidence = complete_evidence();
    evidence.gpu.address = UINT64_MAX - 0x100u;
    evidence.gpu.size = 0x200u;
    plan = polaris_a630_make_plan(evidence);
    CHECK(plan.reason == PolarisA630ReasonInvalidResource);

    printf("PASS A630 policy: %u checks\n", checks);
    return 0;
}
