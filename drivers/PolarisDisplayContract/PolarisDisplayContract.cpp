// SPDX-License-Identifier: BSD-2-Clause-Patent
// Polaris display panel resource contract. No MMIO, DSI, GPIO, clocks,
// regulators, backlight, interrupts, firmware, DMA, or GPU operations occur.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <pexpert/pexpert.h>
#include <string.h>

#include "PolarisDisplayPanelProtocol.h"

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
  const bool match = compatibleContains(root, "xiaomi,polaris") &&
                     compatibleContains(root, "qcom,sdm845");
  root->release();
  return match;
}

} // namespace

class PolarisDisplayContract : public IOService {
  OSDeclareDefaultStructors(PolarisDisplayContract)
public:
  IOService *probe(IOService *provider, SInt32 *score) override
  {
    unsigned enabled = 0;
    if (provider == nullptr || !boardIsPolaris() ||
        !PE_parse_boot_argn("polaris-display-probe", &enabled, sizeof(enabled)) ||
        enabled != 1) return nullptr;
    if (score != nullptr) *score += 20;
    return IOService::probe(provider, score);
  }

  bool start(IOService *provider) override
  {
    if (!IOService::start(provider) || !boardIsPolaris()) return false;
    setProperty("polaris-display-contract-version", 1U, 32);
    setProperty("polaris-display-panel-candidates",
                "dsi_jdi_fhd_nt35596s_video_display;"
                "dsi_jdi_fhd_r63452_cmd_display;"
                "dsi_ebbg_fhd_ft8716_video_display;"
                "dsi_ebbg_fhd_ft8719_video_display");
    setProperty("polaris-display-resolution", "1080x2160");
    setProperty("polaris-display-dsi-lanes", 4U, 32);
    setProperty("polaris-display-panel-selected", false);
    setProperty("polaris-display-dsi-writes-allowed", false);
    setProperty("polaris-display-backlight-allowed", false);
    setProperty("polaris-display-gpu-composition-allowed", false);
    setProperty("polaris-display-mmio-performed", false);
    setProperty("polaris-display-darwin-driver-ready", false);
    setProperty("polaris-display-runtime-gate", "polaris-display-probe=1");
    setName("PolarisDisplayContract");
    registerService();
    IOLog("PolarisDisplayContract: candidates published; DSI I/O=0; panel selected=0\n");
    return true;
  }
};

OSDefineMetaClassAndStructors(PolarisDisplayContract, IOService)
