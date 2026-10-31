#include <assert.h>
#include "../drivers/PolarisNfcContract/PolarisNfcPolicy.h"

static void check_bounds_helpers(void)
{
    /* The SE/bus bound rejects impossible controller IDs. */
    assert(polaris_nfc_bus_valid(0));
    assert(polaris_nfc_bus_valid(3));
    assert(polaris_nfc_bus_valid(15));
    assert(!polaris_nfc_bus_valid(16));
    assert(!polaris_nfc_bus_valid(255));

    assert(!polaris_nfc_address_valid(0x00));
    assert(!polaris_nfc_address_valid(0x02));
    assert(polaris_nfc_address_valid(0x03));
    assert(polaris_nfc_address_valid(0x28));
    assert(polaris_nfc_address_valid(0x77));
    assert(!polaris_nfc_address_valid(0x78));

    /* TLMM GPIO bound. */
    assert(polaris_nfc_irq_valid(0));
    assert(polaris_nfc_irq_valid(63));
    assert(polaris_nfc_irq_valid(4095));
    assert(!polaris_nfc_irq_valid(4096));
}

static void check_complete_contract_is_never_hardware_ready(void)
{
    const PolarisNfcEvidence evidence = {1, 1, 1, 1, 1, 1, 3, 0x28, 63};
    const PolarisNfcPlan plan = polaris_nfc_make_plan(evidence);
    assert(plan.resource_contract_valid == 1);
    assert(plan.reason == PolarisNfcReasonHardwareValidationRequired);
    assert(plan.i2c_writes_allowed == 0);
    assert(plan.interrupts_allowed == 0);
    assert(plan.firmware_load_allowed == 0);
    assert(plan.secure_element_allowed == 0);
}

/* Each malformed or absent DT field must map to its own reason and leave the
 * contract invalid with no capability flags set. */
static void check_fail_closed_reasons(void)
{
    const PolarisNfcEvidence complete = {1, 1, 1, 1, 1, 1, 3, 0x28, 63};
    PolarisNfcEvidence evidence;
    PolarisNfcPlan plan;

    evidence = complete;
    evidence.board_matches = 0;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonBoardMismatch);

    /* No nq@28 / PN54x node in the DT. */
    evidence = complete;
    evidence.controller_present = 0;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonControllerMissing);
    assert(plan.resource_contract_valid == 0);

    /* Node present but not under an I2C controller. */
    evidence = complete;
    evidence.bus_present = 0;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonInvalidBus);

    /* Node present but the bus index is not a real QUPv3 SE. */
    evidence = complete;
    evidence.i2c_bus = 16;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonInvalidBus);

    /* reg property missing or unparsable. */
    evidence = complete;
    evidence.address_valid = 0;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonInvalidAddress);

    /* reg parsed but out of the 7-bit range. */
    evidence = complete;
    evidence.address7 = 0x00;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonInvalidAddress);
    evidence = complete;
    evidence.address7 = 0x78;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonInvalidAddress);

    /* interrupts property missing. */
    evidence = complete;
    evidence.irq_present = 0;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonInvalidIrq);

    /* interrupts parsed but the GPIO is outside TLMM. */
    evidence = complete;
    evidence.irq_gpio = 4096;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonInvalidIrq);

    /* Firmware blobs were never validated. */
    evidence = complete;
    evidence.firmware_complete = 0;
    plan = polaris_nfc_make_plan(evidence);
    assert(plan.reason == PolarisNfcReasonFirmwareIncomplete);

    /* Every failure path must be inert. */
    const uint32_t reasons[] = {
        PolarisNfcReasonBoardMismatch,
        PolarisNfcReasonControllerMissing,
        PolarisNfcReasonInvalidBus,
        PolarisNfcReasonInvalidAddress,
        PolarisNfcReasonInvalidIrq,
        PolarisNfcReasonFirmwareIncomplete,
    };
    for (unsigned i = 0; i < sizeof(reasons) / sizeof(reasons[0]); ++i) {
        evidence = complete;
        switch (reasons[i]) {
        case PolarisNfcReasonBoardMismatch: evidence.board_matches = 0; break;
        case PolarisNfcReasonControllerMissing: evidence.controller_present = 0; break;
        case PolarisNfcReasonInvalidBus: evidence.bus_present = 0; break;
        case PolarisNfcReasonInvalidAddress: evidence.address_valid = 0; break;
        case PolarisNfcReasonInvalidIrq: evidence.irq_present = 0; break;
        case PolarisNfcReasonFirmwareIncomplete: evidence.firmware_complete = 0; break;
        default: assert(0); break;
        }
        plan = polaris_nfc_make_plan(evidence);
        assert(plan.reason == reasons[i]);
        assert(plan.resource_contract_valid == 0);
        assert(plan.i2c_writes_allowed == 0);
        assert(plan.interrupts_allowed == 0);
        assert(plan.firmware_load_allowed == 0);
        assert(plan.secure_element_allowed == 0);
    }
}

int main(void)
{
    check_bounds_helpers();
    check_complete_contract_is_never_hardware_ready();
    check_fail_closed_reasons();
    return 0;
}
