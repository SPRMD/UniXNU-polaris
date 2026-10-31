#include <assert.h>
#include "../drivers/PolarisCameraContract/PolarisCameraPolicy.h"

int main(void)
{
    uint8_t kind = 0;
    assert(polaris_camera_sensor_name_kind("imx363", 6, &kind));
    assert(kind == PolarisCameraSensorImx363);
    assert(polaris_camera_sensor_name_kind("sony,imx363", 11, &kind));
    assert(kind == PolarisCameraSensorImx363);
    assert(!polaris_camera_sensor_name_kind("unknown", 7, &kind));

    PolarisCameraEvidence evidence = {1, 1, 1, 1, 1, 1, 1,
                                      PolarisCameraSensorImx363, 0x34};
    PolarisCameraPlan plan = polaris_camera_make_plan(evidence);
    assert(plan.resource_contract_valid == 1);
    assert(plan.reason == PolarisCameraReasonHardwareValidationRequired);
    assert(plan.cci_reads_allowed == 0);
    assert(plan.sensor_power_allowed == 0);
    assert(plan.csi_dma_allowed == 0);
    assert(plan.firmware_load_allowed == 0);

    evidence.sensor_id_confirmed = 0;
    plan = polaris_camera_make_plan(evidence);
    assert(plan.reason == PolarisCameraReasonSensorIdentityRequired);
    evidence.sensor_id_confirmed = 1;
    evidence.cci_present = 0;
    plan = polaris_camera_make_plan(evidence);
    assert(plan.reason == PolarisCameraReasonMissingCci);
    return 0;
}
