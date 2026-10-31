// SPDX-License-Identifier: BSD-2-Clause-Patent
// PN54x/NCI board contract only. No I2C, GPIO, IRQ, firmware, DMA or SE I/O.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSIterator.h>
#include <pexpert/pexpert.h>
#include <stdint.h>
#include <string.h>

#include "PolarisNfcPolicy.h"

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

static bool candidateNode(IORegistryEntry *entry)
{
  if (entry == nullptr) return false;
  const char *name = entry->getName();
  if (name != nullptr &&
      (strstr(name, "nfc") != nullptr || strstr(name, "nq") != nullptr ||
       strstr(name, "pn5") != nullptr || strstr(name, "pn54") != nullptr)) {
    return true;
  }
  return compatibleContains(entry, "qcom,nq-nci") ||
         compatibleContains(entry, "nxp,pn553") ||
         compatibleContains(entry, "nxp,pn54x");
}

static unsigned countCandidates(IORegistryEntry *entry, unsigned depth)
{
  if (entry == nullptr || depth > 24) return 0;
  unsigned count = candidateNode(entry) ? 1U : 0U;
  OSIterator *children = entry->getChildIterator(gIODTPlane);
  if (children == nullptr) return count;
  while (IORegistryEntry *child = OSDynamicCast(IORegistryEntry,
                                                 children->getNextObject())) {
    count += countCandidates(child, depth + 1);
  }
  children->release();
  return count;
}

} // namespace

class PolarisNfcContract : public IOService {
  OSDeclareDefaultStructors(PolarisNfcContract)

public:
  IOService *probe(IOService *provider, SInt32 *score) override
  {
    unsigned enabled = 0;
    if (provider == nullptr || !boardIsPolaris() ||
        !PE_parse_boot_argn("polaris-nfc-probe", &enabled, sizeof(enabled)) ||
        enabled != 1) return nullptr;
    if (score != nullptr) *score += 20;
    return IOService::probe(provider, score);
  }

  bool start(IOService *provider) override
  {
    if (!IOService::start(provider) || !boardIsPolaris()) return false;
    const unsigned candidates = countCandidates(provider, 0);
    PolarisNfcEvidence evidence = {};
    evidence.board_matches = 1;
    evidence.controller_present = candidates != 0;
    evidence.bus_present = 1;
    evidence.address_valid = 1;
    evidence.irq_present = 1;
    evidence.i2c_bus = 3;
    evidence.address7 = 0x28;
    evidence.irq_gpio = 63;
    evidence.firmware_complete = 0;
    const PolarisNfcPlan plan = polaris_nfc_make_plan(evidence);

    setProperty("polaris-nfc-contract-version", 1U, 32);
    setProperty("polaris-nfc-controller", "NXP PN553/PN54x candidate");
    setProperty("polaris-nfc-i2c-bus-candidate", 3U, 32);
    setProperty("polaris-nfc-i2c-address-candidate", 0x28U, 32);
    setProperty("polaris-nfc-irq-gpio-candidate", 63U, 32);
    setProperty("polaris-nfc-candidate-nodes", candidates, 32);
    setProperty("polaris-nfc-resource-contract-valid",
                plan.resource_contract_valid, 32);
    setProperty("polaris-nfc-plan-reason", plan.reason, 32);
    setProperty("polaris-nfc-i2c-writes-allowed",
                plan.i2c_writes_allowed, 32);
    setProperty("polaris-nfc-interrupts-allowed",
                plan.interrupts_allowed, 32);
    setProperty("polaris-nfc-firmware-load-allowed",
                plan.firmware_load_allowed, 32);
    setProperty("polaris-nfc-secure-element-allowed",
                plan.secure_element_allowed, 32);
    setProperty("polaris-nfc-i2c-reads-performed", false);
    setProperty("polaris-nfc-i2c-writes-performed", false);
    setProperty("polaris-nfc-interrupts-claimed", false);
    setProperty("polaris-nfc-firmware-loaded", false);
    setProperty("polaris-nfc-secure-element-published", false);
    setProperty("polaris-nfc-darwin-driver-ready", false);
    setProperty("polaris-nfc-runtime-gate", "polaris-nfc-probe=1");
    setName("PolarisNfcContract");
    registerService();
    IOLog("PolarisNfcContract: candidates=%u; I2C=0 IRQ=0 firmware=0 SE=0\n",
          candidates);
    return true;
  }
};

OSDefineMetaClassAndStructors(PolarisNfcContract, IOService)
