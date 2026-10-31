// SPDX-License-Identifier: BSD-2-Clause-Patent
// PN54x/NCI board contract only. No I2C, GPIO, IRQ, firmware, DMA or SE I/O.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSIterator.h>
#include <pexpert/pexpert.h>
#include <stdint.h>
#include <string.h>

#include "../PolarisGeniI2c/PolarisGeniI2cResources.h"
#include "PolarisNfcPolicy.h"

namespace {

/* The candidate values come from the existing board resource table
 * (PolarisGeniI2cResources.h: qupv3_se3_i2c, PN54x at 0x28, GPIO63 IRQ) instead
 * of being duplicated here.  They are expectations to compare the DT against,
 * never assumptions about what the DT contains. */
static PolarisGeniI2cResource nfcCandidate()
{
  PolarisGeniI2cResource resource = {};
  if (!polaris_geni_i2c_resource(PolarisGeniI2cNfc, &resource)) {
    resource = PolarisGeniI2cResource{};
  }
  return resource;
}

static bool polarisCStringContains(const char *haystack, const char *needle)
{
  if (haystack == nullptr || needle == nullptr) return false;
  if (*needle == '\0') return true;
  for (const char *start = haystack; *start != '\0'; ++start) {
    const char *left = start;
    const char *right = needle;
    while (*left != '\0' && *right != '\0' && *left == *right) {
      ++left;
      ++right;
    }
    if (*right == '\0') return true;
  }
  return false;
}

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
      (polarisCStringContains(name, "nfc") || polarisCStringContains(name, "nq") ||
       polarisCStringContains(name, "pn5") || polarisCStringContains(name, "pn54"))) {
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

static bool parentIsI2cController(IORegistryEntry *entry);

/* A name such as "nfc" or "nfc_int_active" also matches the TLMM pinctrl state
 * nodes, which carry neither a reg nor a bus.  Only a candidate that sits under
 * an I2C controller is a real controller candidate. */
static bool isControllerCandidate(IORegistryEntry *entry)
{
  return entry != nullptr && candidateNode(entry) && parentIsI2cController(entry);
}

static unsigned countControllerCandidates(IORegistryEntry *entry, unsigned depth)
{
  if (entry == nullptr || depth > 24) return 0;
  unsigned count = isControllerCandidate(entry) ? 1U : 0U;
  OSIterator *children = entry->getChildIterator(gIODTPlane);
  if (children == nullptr) return count;
  while (IORegistryEntry *child = OSDynamicCast(IORegistryEntry,
                                                 children->getNextObject())) {
    count += countControllerCandidates(child, depth + 1);
  }
  children->release();
  return count;
}

/* Prefer a controller candidate (I2C child) over a bare name match so a
 * pinctrl state node can never be mistaken for the NFC controller. */
static IORegistryEntry *firstControllerCandidate(IORegistryEntry *entry,
                                                 unsigned depth)
{
  if (entry == nullptr || depth > 24) return nullptr;
  if (isControllerCandidate(entry)) return entry;
  OSIterator *children = entry->getChildIterator(gIODTPlane);
  if (children == nullptr) return nullptr;
  IORegistryEntry *found = nullptr;
  while (IORegistryEntry *child = OSDynamicCast(IORegistryEntry,
                                                 children->getNextObject())) {
    found = firstControllerCandidate(child, depth + 1);
    if (found != nullptr) break;
  }
  children->release();
  return found;
}

static IORegistryEntry *firstCandidate(IORegistryEntry *entry, unsigned depth)
{
  if (entry == nullptr || depth > 24) return nullptr;
  if (candidateNode(entry)) return entry;
  OSIterator *children = entry->getChildIterator(gIODTPlane);
  if (children == nullptr) return nullptr;
  IORegistryEntry *found = nullptr;
  while (IORegistryEntry *child = OSDynamicCast(IORegistryEntry,
                                                 children->getNextObject())) {
    found = firstCandidate(child, depth + 1);
    if (found != nullptr) break;
  }
  children->release();
  return found;
}

static uint32_t cellAt(const uint8_t *bytes, size_t index)
{
  const uint8_t *cell = bytes + index * 4;
  return ((uint32_t)cell[0] << 24) | ((uint32_t)cell[1] << 16) |
         ((uint32_t)cell[2] << 8) | (uint32_t)cell[3];
}

/* reg = <7-bit-address> when the I2C parent declares #size-cells = 0 (as the
 * reference DTB does for i2c@88c000), or <bus-address 7-bit-address> when it
 * declares #size-cells = 1.  The last cell is the I2C address in both cases. */
static bool nodeAddress7(IORegistryEntry *entry, uint8_t *address7)
{
  OSData *data = OSDynamicCast(OSData, entry->getProperty("reg"));
  if (data == nullptr || data->getBytesNoCopy() == nullptr) return false;
  const size_t length = data->getLength();
  if (length != 4 && length != 8) return false;
  const uint8_t *bytes = static_cast<const uint8_t *>(data->getBytesNoCopy());
  const uint32_t last = cellAt(bytes, length / 4 - 1);
  if (last > 0x7fU) return false;
  *address7 = (uint8_t)last;
  return true;
}

/* The interrupt specifier width comes from the parent's #interrupt-cells.  The
 * reference Polaris DTB routes nq@28 to the TLMM pinctrl node, which declares
 * #interrupt-cells = 2, so the property is <gpio flags>.  A 3-cell
 * <type gpio flags> form is also accepted; anything else is treated as
 * unparsable so the plan fails closed instead of guessing a GPIO. */
static bool nodeIrqGpio(IORegistryEntry *entry, uint32_t *irq_gpio)
{
  OSData *data = OSDynamicCast(OSData, entry->getProperty("interrupts"));
  if (data == nullptr || data->getBytesNoCopy() == nullptr) return false;
  const size_t length = data->getLength();
  if (length == 0 || (length % 4) != 0) return false;
  const size_t cells = length / 4;
  if (cells != 2 && cells != 3) return false;
  const uint8_t *bytes = static_cast<const uint8_t *>(data->getBytesNoCopy());
  *irq_gpio = cells == 2 ? cellAt(bytes, 0) : cellAt(bytes, 1);
  return true;
}

static bool parentIsI2cController(IORegistryEntry *entry)
{
  if (entry == nullptr) return false;
  IORegistryEntry *parent = entry->getParentEntry(gIODTPlane);
  if (parent == nullptr) return false;
  const char *name = parent->getName();
  return name != nullptr && polarisCStringContains(name, "i2c");
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
    const unsigned nameMatches = countCandidates(provider, 0);
    const unsigned controllers = countControllerCandidates(provider, 0);
    IORegistryEntry *node =
        controllers != 0 ? firstControllerCandidate(provider, 0)
                         : (nameMatches != 0 ? firstCandidate(provider, 0) : nullptr);

    /* Every field below is read from the DT; nothing is assumed because the
     * board matched.  A missing or malformed node therefore fails closed in
     * polaris_nfc_make_plan instead of publishing a valid contract. */
    uint8_t address7 = 0;
    uint32_t irqGpio = 0;
    const bool addressParsed = node != nullptr && nodeAddress7(node, &address7);
    const bool irqParsed = node != nullptr && nodeIrqGpio(node, &irqGpio);
    const bool busPresent = node != nullptr && parentIsI2cController(node);

    PolarisNfcEvidence evidence = {};
    evidence.board_matches = 1;
    evidence.controller_present = node != nullptr;
    evidence.bus_present = busPresent ? 1 : 0;
    evidence.address_valid = addressParsed ? 1 : 0;
    evidence.irq_present = irqParsed ? 1 : 0;
    evidence.firmware_complete = 0;
    const PolarisGeniI2cResource candidate = nfcCandidate();
    evidence.i2c_bus = candidate.bus_index;
    evidence.address7 = address7;
    evidence.irq_gpio = irqGpio;
    const PolarisNfcPlan plan = polaris_nfc_make_plan(evidence);

    setProperty("polaris-nfc-contract-version", 1U, 32);
    setProperty("polaris-nfc-controller", "NXP PN553/PN54x candidate");
    setProperty("polaris-nfc-i2c-bus-candidate", candidate.bus_index, 32);
    setProperty("polaris-nfc-i2c-bus-source",
                "candidate; QUPv3 SE number is not parsed from the DT");
    setProperty("polaris-nfc-i2c-parent-confirmed", busPresent);
    setProperty("polaris-nfc-i2c-address-candidate", candidate.address7, 32);
    setProperty("polaris-nfc-i2c-address-observed", addressParsed ? address7 : 0U, 32);
    setProperty("polaris-nfc-i2c-address-matches-candidate",
                addressParsed && address7 == candidate.address7);
    setProperty("polaris-nfc-irq-gpio-candidate", candidate.irq_gpio, 32);
    setProperty("polaris-nfc-irq-gpio-observed", irqParsed ? irqGpio : 0U, 32);
    setProperty("polaris-nfc-irq-gpio-matches-candidate",
                irqParsed && irqGpio == (uint32_t)candidate.irq_gpio);
    setProperty("polaris-nfc-candidate-nodes", nameMatches, 32);
    /* Pinctrl state nodes ("nfc", "nfc_int_active", ...) match by name but are
     * not controllers; this count is the honest one. */
    setProperty("polaris-nfc-controller-candidate-nodes", controllers, 32);
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
    IOLog("PolarisNfcContract: controllers=%u names=%u reason=%u; "
          "I2C=0 IRQ=0 firmware=0 SE=0\n",
          controllers, nameMatches, plan.reason);
    return true;
  }
};

OSDefineMetaClassAndStructors(PolarisNfcContract, IOService)
