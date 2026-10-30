// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Board-gated PMIC/input observer contract for Xiaomi MIX 2S (polaris).
// This service enumerates candidate DT resources and publishes a bounded
// read-only SPMI plan. It deliberately performs no SPMI/MMIO access, GPIO
// changes, interrupt registration, HID publication or power-source work.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <pexpert/pexpert.h>
#include <stdint.h>
#include <string.h>

#include "PolarisPmicInputProtocol.h"

extern "C" {
volatile uint32_t polaris_pmic_input_started = 0;
volatile uint32_t polaris_pmic_input_spmi_reads = 0;
volatile uint32_t polaris_pmic_input_hid_published = 0;
volatile uint32_t polaris_pmic_input_power_source_published = 0;
}

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
        memcmp(bytes + offset, wanted, wantedLength) == 0)
      return true;
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

static unsigned countCandidateNodes(IORegistryEntry *entry, unsigned depth)
{
  if (entry == nullptr || depth > 16) return 0;
  unsigned count = 0;
  const char *name = entry->getName();
  if ((name != nullptr &&
       (strstr(name, "pmic") != nullptr || strstr(name, "spmi") != nullptr ||
        strstr(name, "pon") != nullptr || strstr(name, "fuel-gauge") != nullptr ||
        strstr(name, "battery") != nullptr || strstr(name, "gpio-keys") != nullptr)) ||
      compatibleContains(entry, "qcom,pm8998") ||
      compatibleContains(entry, "qcom,pmi8998") ||
      compatibleContains(entry, "qcom,qpnp-power-on") ||
      compatibleContains(entry, "qcom,pm8998-fg")) {
    ++count;
  }
  OSIterator *children = entry->getChildIterator(gIODTPlane);
  if (children == nullptr) return count;
  while (IORegistryEntry *child = OSDynamicCast(IORegistryEntry,
                                                 children->getNextObject())) {
    count += countCandidateNodes(child, depth + 1);
  }
  children->release();
  return count;
}

} // namespace

class PolarisPmicInput : public IOService {
  OSDeclareDefaultStructors(PolarisPmicInput)

public:
  IOService *probe(IOService *provider, SInt32 *score) override
  {
    unsigned enabled = 0;
    if (provider == nullptr || !boardIsPolaris() ||
        !PE_parse_boot_argn("polaris-pmic-input", &enabled, sizeof(enabled)) ||
        enabled != 1) {
      return nullptr;
    }
    if (score != nullptr) *score += 35;
    return IOService::probe(provider, score);
  }

  bool start(IOService *provider) override
  {
    if (!IOService::start(provider) || !boardIsPolaris()) return false;
    setProperty("polaris-pmic-input-contract-version", 1U, 32);
    setProperty("polaris-pmic-input-mode", "read-only-spmi-observer");
    setProperty("polaris-pmic-input-pmic-family", "PMI8998/PM8998 candidate");
    setProperty("polaris-pmic-input-read-plan-count", 5U, 32);
    setProperty("polaris-pmic-input-candidate-nodes",
                countCandidateNodes(provider, 0), 32);
    setProperty("polaris-pmic-input-spmi-read-only", true);
    setProperty("polaris-pmic-input-spmi-writes-performed", false);
    setProperty("polaris-pmic-input-mmio-performed", false);
    setProperty("polaris-pmic-input-gpio-changes-performed", false);
    setProperty("polaris-pmic-input-interrupts-claimed", false);
    setProperty("polaris-pmic-input-hid-published", false);
    setProperty("polaris-pmic-input-power-source-published", false);
    setProperty("polaris-pmic-input-darwin-driver-ready", false);
    setProperty("polaris-pmic-input-runtime-gate", "polaris-pmic-input=1");
    setName("PolarisPmicInput");
    registerService();
    polaris_pmic_input_started = 1;
    IOLog("PolarisPmicInput: observer contract published; SPMI=read-only HID=0 power=0\\n");
    return true;
  }
};

OSDefineMetaClassAndStructors(PolarisPmicInput, IOService)
