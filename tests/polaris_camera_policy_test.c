#include <assert.h>
#include "../drivers/PolarisCameraContract/PolarisCameraPolicy.h"

static void check_sensor_name_kind(void)
{
    uint8_t kind = 0;
    assert(polaris_camera_sensor_name_kind("imx363", 6, &kind));
    assert(kind == PolarisCameraSensorImx363);
    assert(polaris_camera_sensor_name_kind("sony,imx363", 11, &kind));
    assert(kind == PolarisCameraSensorImx363);
    assert(polaris_camera_sensor_name_kind("ov5675", 6, &kind));
    assert(kind == PolarisCameraSensorOv5675);
    assert(polaris_camera_sensor_name_kind("s5k3m3", 6, &kind));
    assert(kind == PolarisCameraSensorS5k3m3);

    kind = 0xff;
    assert(!polaris_camera_sensor_name_kind("unknown", 7, &kind));
    assert(kind == 0xff);
    /* The reference DTB carries only generic "qcom,cam-sensor" nodes; that
     * name must not be mistaken for a known sensor identity. */
    assert(!polaris_camera_sensor_name_kind("qcom,cam-sensor", 15, &kind));
    assert(!polaris_camera_sensor_name_kind("imx36", 5, &kind));
    assert(!polaris_camera_sensor_name_kind("", 0, &kind));
    assert(!polaris_camera_sensor_name_kind(NULL, 6, &kind));
    assert(!polaris_camera_sensor_name_kind("imx363", 6, NULL));
}

static void check_address_bounds(void)
{
    assert(!polaris_camera_address_valid(0x00));
    assert(!polaris_camera_address_valid(0x02));
    assert(polaris_camera_address_valid(0x03));
    assert(polaris_camera_address_valid(0x34));
    assert(polaris_camera_address_valid(0x77));
    assert(!polaris_camera_address_valid(0x78));
    assert(!polaris_camera_address_valid(0xff));
}

static void check_complete_contract_is_never_hardware_ready(void)
{
    PolarisCameraEvidence evidence = {1, 1, 1, 1, 1, 1, 1,
                                      PolarisCameraSensorImx363, 0x34};
    const PolarisCameraPlan plan = polaris_camera_make_plan(evidence);
    assert(plan.resource_contract_valid == 1);
    assert(plan.reason == PolarisCameraReasonHardwareValidationRequired);
    assert(plan.cci_reads_allowed == 0);
    assert(plan.sensor_power_allowed == 0);
    assert(plan.csi_dma_allowed == 0);
    assert(plan.firmware_load_allowed == 0);
}

/* Each malformed or absent DT node must map to its own reason, and no plan may
 * ever set a capability flag. */
static void check_fail_closed_reasons(void)
{
    const PolarisCameraEvidence complete = {1, 1, 1, 1, 1, 1, 1,
                                            PolarisCameraSensorImx363, 0x34};
    PolarisCameraPlan plan;
    PolarisCameraEvidence evidence;

    evidence = complete;
    evidence.board_matches = 0;
    plan = polaris_camera_make_plan(evidence);
    assert(plan.reason == PolarisCameraReasonBoardMismatch);

    evidence = complete;
    evidence.cci_present = 0;
    plan = polaris_camera_make_plan(evidence);
    assert(plan.reason == PolarisCameraReasonMissingCci);

    /* CSIPHY and CSID are checked independently. */
    evidence = complete;
    evidence.csiphy_present = 0;
    plan = polaris_camera_make_plan(evidence);
    assert(plan.reason == PolarisCameraReasonMissingCsi);
    evidence = complete;
    evidence.csid_present = 0;
    plan = polaris_camera_make_plan(evidence);
    assert(plan.reason == PolarisCameraReasonMissingCsi);

    /* No sensor node at all is a distinct, non-misleading reason. */
    evidence = complete;
    evidence.sensor_candidate = 0;
    plan = polaris_camera_make_plan(evidence);
    assert(plan.reason == PolarisCameraReasonMissingSensor);
    assert(plan.resource_contract_valid == 0);

    /* A matched node with no readable identity must not be assumed to be an
     * IMX363 just because a sensor node exists. */
    evidence = complete;
    evidence.sensor_kind = PolarisCameraSensorUnknown;
    plan = polaris_camera_make_plan(evidence);
    assert(plan.reason == PolarisCameraReasonSensorIdentityRequired);
    assert(plan.resource_contract_valid == 0);

    /* Out-of-range addresses are a distinct failure from an absent node. */
    evidence = complete;
    evidence.address7 = 0x00;
    plan = polaris_camera_make_plan(evidence);
    assert(plan.reason == PolarisCameraReasonInvalidSensorAddress);
    evidence = complete;
    evidence.address7 = 0x78;
    plan = polaris_camera_make_plan(evidence);
    assert(plan.reason == PolarisCameraReasonInvalidSensorAddress);

    /* Identity was never confirmed by reading the sensor ID register. */
    evidence = complete;
    evidence.sensor_id_confirmed = 0;
    plan = polaris_camera_make_plan(evidence);
    assert(plan.reason == PolarisCameraReasonSensorIdentityRequired);

    /* Tuning blobs were never validated. */
    evidence = complete;
    evidence.tuning_complete = 0;
    plan = polaris_camera_make_plan(evidence);
    assert(plan.reason == PolarisCameraReasonFirmwareIncomplete);

    /* Every failure path must leave all capability flags at zero. */
    const uint32_t reasons[] = {
        PolarisCameraReasonBoardMismatch,
        PolarisCameraReasonMissingCci,
        PolarisCameraReasonMissingCsi,
        PolarisCameraReasonMissingSensor,
        PolarisCameraReasonInvalidSensorAddress,
        PolarisCameraReasonSensorIdentityRequired,
        PolarisCameraReasonFirmwareIncomplete,
    };
    for (unsigned i = 0; i < sizeof(reasons) / sizeof(reasons[0]); ++i) {
        assert(reasons[i] != PolarisCameraReasonNone);
    }
    for (unsigned i = 0; i < sizeof(reasons) / sizeof(reasons[0]); ++i) {
        evidence = complete;
        switch (reasons[i]) {
        case PolarisCameraReasonBoardMismatch: evidence.board_matches = 0; break;
        case PolarisCameraReasonMissingCci: evidence.cci_present = 0; break;
        case PolarisCameraReasonMissingCsi: evidence.csiphy_present = 0; break;
        case PolarisCameraReasonMissingSensor: evidence.sensor_candidate = 0; break;
        case PolarisCameraReasonInvalidSensorAddress: evidence.address7 = 0; break;
        case PolarisCameraReasonSensorIdentityRequired:
            evidence.sensor_kind = PolarisCameraSensorUnknown;
            break;
        case PolarisCameraReasonFirmwareIncomplete: evidence.tuning_complete = 0; break;
        default: assert(0); break;
        }
        plan = polaris_camera_make_plan(evidence);
        assert(plan.reason == reasons[i]);
        assert(plan.resource_contract_valid == 0);
        assert(plan.cci_reads_allowed == 0);
        assert(plan.sensor_power_allowed == 0);
        assert(plan.csi_dma_allowed == 0);
        assert(plan.firmware_load_allowed == 0);
    }
}

int main(void)
{
    check_sensor_name_kind();
    check_address_bounds();
    check_complete_contract_is_never_hardware_ready();
    check_fail_closed_reasons();
    return 0;
}
