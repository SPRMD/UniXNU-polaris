#include <assert.h>
#include "../drivers/PolarisNfcContract/PolarisNfcPolicy.h"

int main(void)
{
    PolarisNfcEvidence evidence = {1, 1, 1, 1, 1, 1, 3, 0x28, 63};
    PolarisNfcPlan plan = polaris_nfc_make_plan(evidence);
    assert(plan.resource_contract_valid == 1);
    assert(plan.reason == PolarisNfcReasonHardwareValidationRequired);
    assert(plan.i2c_writes_allowed == 0);
    assert(plan.interrupts_allowed == 0);
    assert(plan.firmware_load_allowed == 0);
    assert(plan.secure_element_allowed == 0);

    evidence.firmware_complete = 0;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonFirmwareIncomplete);
    evidence.address7 = 0x00;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonInvalidAddress);
    evidence.address7 = 0x28;
    evidence.board_matches = 0;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonBoardMismatch);
    return 0;
}
