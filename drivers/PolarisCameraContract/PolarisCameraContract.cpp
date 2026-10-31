// SPDX-License-Identifier: BSD-2-Clause-Patent
// CCI/CSIPHY/CSID camera contract only. No sensor or CSI hardware I/O.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSIterator.h>
#include <pexpert/pexpert.h>
#include <stdint.h>
#include <string.h>

#include "PolarisCameraPolicy.h"

namespace {

static bool compatibleContains(IORegistryEntry *entry, const char *wanted)
{
  if (entry == nullptr || wanted == nullptr) return false;
  OSData *data = OSDynamicCast(OSData, entry->getProperty("compatible"));
  if (data == nullptr || data->getBytesNoCopy() == nullptr) return false;
  const char *bytes = static_cast<const char *>(data->getBytesNoCopy());
  const size_t length = data->getLength();
  const size_t wantedLength = strlen(wanted);
  for (size_t offset = 0; offset < length;) {
    size_t end = offset;
    while (end < length && bytes[end] != '\0') ++end;
    if (end - offset == wantedLength &&
        memcmp(bytes + offset, wanted, wantedLength) == 0) return true;
    offset = end < length ? end + 1 : length;
  }
  return false;
}

static bool boardIsPolaris()
{
  IORegistryEntry *root = IORegistryEntry::fromPath("/", gIODTPlane);
  if (root == nullptr) return false;
  const bool result = compatibleContains(root, "xiaomi,polaris") &&
                      compatibleContains(root, "qcom,sdm845");
  root->release();
  return result;
}

static bool hasNameOrCompatible(IORegistryEntry *entry,
                                const char *const *names, unsigned nameCount,
                                const char *const *compatibles,
                                unsigned compatibleCount)
{
  if (entry == nullptr) return false;
  const char *name = entry->getName();
  for (unsigned i = 0; i < nameCount; ++i) {
    if (name != nullptr && strstr(name, names[i]) != nullptr) return true;
  }
  for (unsigned i = 0; i < compatibleCount; ++i) {
    if (compatibleContains(entry, compatibles[i])) return true;
  }
  return false;
}

static unsigned countKind(IORegistryEntry *entry, unsigned depth,
                          const char *const *names, unsigned nameCount,
                          const char *const *compatibles,
                          unsigned compatibleCount)
{
  if (entry == nullptr || depth > 24) return 0;
  unsigned count = hasNameOrCompatible(entry, names, nameCount,
                                       compatibles, compatibleCount) ? 1U : 0U;
  OSIterator *children = entry->getChildIterator(gIODTPlane);
  if (children == nullptr) return count;
  while (IORegistryEntry *child = OSDynamicCast(IORegistryEntry,
                                                 children->getNextObject())) {
    count += countKind(child, depth + 1, names, nameCount,
                       compatibles, compatibleCount);
  }
  children->release();
  return count;
}

} // namespace

class PolarisCameraContract : public IOService {
  OSDeclareDefaultStructors(PolarisCameraContract)

public:
  IOService *probe(IOService *provider, SInt32 *score) override
  {
    unsigned enabled = 0;
    if (provider == nullptr || !boardIsPolaris() ||
        !PE_parse_boot_argn("polaris-camera-probe", &enabled, sizeof(enabled)) ||
        enabled != 1) return nullptr;
    if (score != nullptr) *score += 20;
    return IOService::probe(provider, score);
  }

  bool start(IOService *provider) override
  {
    if (!IOService::start(provider) || !boardIsPolaris()) return false;
    static const char *const cciNames[] = {"cci"};
    static const char *const cciCompat[] = {"qcom,cci"};
    static const char *const csiphyNames[] = {"csiphy"};
    static const char *const csiphyCompat[] = {"qcom,csiphy"};
    static const char *const csidNames[] = {"csid"};
    static const char *const csidCompat[] = {"qcom,csid"};
    static const char *const sensorNames[] = {"imx363", "ov5675", "s5k3m3",
                                               "cam-sensor"};
    static const char *const sensorCompat[] = {"sony,imx363",
                                               "ovti,ov5675",
                                               "samsung,s5k3m3",
                                               "qcom,cam-sensor"};
    const unsigned cci = countKind(provider, 0, cciNames, 1, cciCompat, 1);
    const unsigned csiphy = countKind(provider, 0, csiphyNames, 1,
                                      csiphyCompat, 1);
    const unsigned csid = countKind(provider, 0, csidNames, 1,
                                    csidCompat, 1);
    const unsigned sensors = countKind(provider, 0, sensorNames, 4,
                                       sensorCompat, 4);

    PolarisCameraEvidence evidence = {};
    evidence.board_matches = 1;
    evidence.cci_present = cci != 0;
    evidence.csiphy_present = csiphy != 0;
    evidence.csid_present = csid != 0;
    evidence.sensor_candidate = sensors != 0;
    evidence.sensor_kind = PolarisCameraSensorImx363;
    evidence.address7 = 0x34;
    evidence.sensor_id_confirmed = 0;
    evidence.tuning_complete = 0;
    const PolarisCameraPlan plan = polaris_camera_make_plan(evidence);

    setProperty("polaris-camera-contract-version", 1U, 32);
    setProperty("polaris-camera-sensor-candidates",
                "Sony IMX363,OmniVision OV5675,Samsung S5K3M3");
    setProperty("polaris-camera-imx363-cci-address-candidate", 0x34U, 32);
    setProperty("polaris-camera-imx363-id-register", 0x0016U, 32);
    setProperty("polaris-camera-imx363-id-candidate", 0x0363U, 32);
    setProperty("polaris-camera-cci-nodes", cci, 32);
    setProperty("polaris-camera-csiphy-nodes", csiphy, 32);
    setProperty("polaris-camera-csid-nodes", csid, 32);
    setProperty("polaris-camera-sensor-nodes", sensors, 32);
    setProperty("polaris-camera-resource-contract-valid",
                plan.resource_contract_valid, 32);
    setProperty("polaris-camera-plan-reason", plan.reason, 32);
    setProperty("polaris-camera-cci-reads-allowed",
                plan.cci_reads_allowed, 32);
    setProperty("polaris-camera-sensor-power-allowed",
                plan.sensor_power_allowed, 32);
    setProperty("polaris-camera-csi-dma-allowed", plan.csi_dma_allowed, 32);
    setProperty("polaris-camera-firmware-load-allowed",
                plan.firmware_load_allowed, 32);
    setProperty("polaris-camera-cci-reads-performed", false);
    setProperty("polaris-camera-sensor-power-enabled", false);
    setProperty("polaris-camera-csi-dma-created", false);
    setProperty("polaris-camera-firmware-loaded", false);
    setProperty("polaris-camera-darwin-driver-ready", false);
    setProperty("polaris-camera-runtime-gate", "polaris-camera-probe=1");
    setName("PolarisCameraContract");
    registerService();
    IOLog("PolarisCameraContract: cci=%u csiphy=%u csid=%u sensors=%u; I/O=0 DMA=0\n",
          cci, csiphy, csid, sensors);
    return true;
  }
};

OSDefineMetaClassAndStructors(PolarisCameraContract, IOService)
