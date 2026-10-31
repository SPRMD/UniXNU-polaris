// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Read-only Polaris resource inventory. This driver intentionally performs
// no MMIO and is gated behind polaris-board-probe=1.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSIterator.h>
#include <pexpert/pexpert.h>
#include <string.h>

extern "C" {
volatile uint32_t polaris_board_probe_active = 0;
volatile uint32_t polaris_board_probe_resources = 0;
volatile uint32_t polaris_board_probe_ufs = 0;
volatile uint32_t polaris_board_probe_gpu = 0;
volatile uint32_t polaris_board_probe_display = 0;
volatile uint32_t polaris_board_probe_smmu = 0;
}

class PolarisBoardProbe : public IOService {
  OSDeclareDefaultStructors (PolarisBoardProbe)
  static bool containsCompatible (IORegistryEntry *entry, const char *wanted);
  static bool nameContains (IORegistryEntry *entry, const char *wanted);
  void publishFacts (IORegistryEntry *provider);
public:
  IOService *probe (IOService *provider, SInt32 *score) override;
  bool start (IOService *provider) override;
};

OSDefineMetaClassAndStructors (PolarisBoardProbe, IOService)

bool PolarisBoardProbe::containsCompatible (IORegistryEntry *entry, const char *wanted)
{
  OSData *data = OSDynamicCast (OSData, entry->getProperty ("compatible"));
  if (data == nullptr || wanted == nullptr) return false;
  const char *bytes = static_cast<const char *> (data->getBytesNoCopy ());
  const size_t length = data->getLength ();
  const size_t wantedLength = strlen (wanted);
  for (size_t offset = 0; offset < length;) {
    size_t end = offset;
    while (end < length && bytes[end] != '\0') ++end;
    if (end - offset == wantedLength && memcmp (bytes + offset, wanted, wantedLength) == 0) return true;
    offset = end < length ? end + 1 : length;
  }
  return false;
}

bool PolarisBoardProbe::nameContains (IORegistryEntry *entry, const char *wanted)
{
  const char *name = entry->getName ();
  return name != nullptr && wanted != nullptr && strstr (name, wanted) != nullptr;
}

static bool polarisBoardMatches (void)
{
  IORegistryEntry *root = IORegistryEntry::fromPath ("/", gIODTPlane);
  if (root == nullptr) return false;
  OSData *compatible = OSDynamicCast (OSData, root->getProperty ("compatible"));
  const char *bytes = compatible != nullptr ? static_cast<const char *>(compatible->getBytesNoCopy ()) : nullptr;
  const size_t length = compatible != nullptr ? compatible->getLength () : 0;
  bool hasPolaris = false, hasSdm845 = false;
  for (size_t offset = 0; bytes != nullptr && offset < length;) {
    size_t end = offset;
    while (end < length && bytes[end] != '\0') ++end;
    const size_t itemLength = end - offset;
    hasPolaris |= itemLength == strlen ("xiaomi,polaris") &&
      memcmp (bytes + offset, "xiaomi,polaris", itemLength) == 0;
    hasSdm845 |= itemLength == strlen ("qcom,sdm845") &&
      memcmp (bytes + offset, "qcom,sdm845", itemLength) == 0;
    offset = end < length ? end + 1 : length;
  }
  root->release ();
  return hasPolaris && hasSdm845;
}

IOService *PolarisBoardProbe::probe (IOService *provider, SInt32 *score)
{
  unsigned enabled = 0;
  PE_parse_boot_argn ("polaris-board-probe", &enabled, sizeof (enabled));
  if (enabled != 1 || provider == nullptr || !polarisBoardMatches ()) return nullptr;
  if (score != nullptr) *score += 50;
  return IOService::probe (provider, score);
}

void PolarisBoardProbe::publishFacts (IORegistryEntry *provider)
{
  uint32_t resources = 0;
  uint32_t ufs = 0, gpu = 0, display = 0, smmu = 0;
  OSIterator *iterator = provider->getChildIterator (gIODTPlane);
  if (iterator != nullptr) {
    while (IORegistryEntry *entry = OSDynamicCast (IORegistryEntry, iterator->getNextObject ())) {
      ++resources;
      if (nameContains (entry, "ufshc") || containsCompatible (entry, "qcom,ufshc")) ufs = 1;
      if (nameContains (entry, "kgsl") || containsCompatible (entry, "qcom,kgsl-3d0")) gpu = 1;
      if (nameContains (entry, "mdss") || containsCompatible (entry, "qcom,sde-kms")) display = 1;
      if (nameContains (entry, "smmu") || containsCompatible (entry, "qcom,smmu-v2")) smmu = 1;
    }
    iterator->release ();
  }

  // These properties are a DT inventory only. In particular, the explicit
  // false value is part of the diagnostic contract: no MMIO occurred.
  setProperty ("polaris-board-probe-active", true);
  setProperty ("polaris-board-mmio-performed", false);
  setProperty ("polaris-board-resource-count", resources, 32);
  setProperty ("polaris-board-ufs-present", ufs, 32);
  setProperty ("polaris-board-gpu-present", gpu, 32);
  setProperty ("polaris-board-display-present", display, 32);
  setProperty ("polaris-board-smmu-present", smmu, 32);
  setProperty ("polaris-board-runtime-gate", "polaris-board-probe=1");

  polaris_board_probe_resources = resources;
  polaris_board_probe_ufs = ufs;
  polaris_board_probe_gpu = gpu;
  polaris_board_probe_display = display;
  polaris_board_probe_smmu = smmu;
  IOLog ("PolarisBoardProbe: %u arm-io resources; UFS=%u GPU=%u display=%u SMMU=%u; MMIO=0\n",
         resources, ufs, gpu, display, smmu);
}

bool PolarisBoardProbe::start (IOService *provider)
{
  if (!IOService::start (provider)) return false;
  publishFacts (provider);
  polaris_board_probe_active = 1;
  registerService ();
  return true;
}
