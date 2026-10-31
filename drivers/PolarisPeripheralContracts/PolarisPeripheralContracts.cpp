// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Board-specific Darwin integration points for the Polaris peripherals.
//
// This archive is deliberately a resource/protocol contract.  It does not
// map MMIO, claim interrupts, toggle GPIOs, vote regulators, create DMA,
// download firmware, or expose a network/camera/NFC userland device.  The
// service is useful because the old Polaris XNU patches already identified
// the WCN3990/WLFW, PN54x/NCI and IMX363/CCI protocol boundaries; the missing
// step was wiring those boundaries into the current UniXNU runtime without
// pretending that Android or WOA binaries are Darwin drivers.

#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOService.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSIterator.h>
#include <pexpert/pexpert.h>
#include <string.h>

#include "../PolarisGeniI2c/PolarisGeniI2cResources.h"
#include "../PolarisTransportContracts/PolarisCciProtocol.h"
#include "../PolarisTransportContracts/PolarisNci.h"
#include "../PolarisTransportContracts/PolarisProtocolSelfTest.h"
#include "../PolarisTransportContracts/PolarisQcaProtocol.h"
#include "../PolarisTransportContracts/PolarisWlfwProtocol.h"

namespace {

enum Subsystem : unsigned {
  kWifi = 0,
  kBluetooth,
  kNfc,
  kCamera,
  kCount,
};

struct Fact {
  unsigned nodes;
  unsigned reg;
  unsigned interrupts;
};

static bool contains(const char *text, const char *wanted)
{
  if (text == nullptr || wanted == nullptr) return false;
  if (*wanted == '\0') return true;
  for (const char *start = text; *start != '\0'; ++start) {
    const char *left = start;
    const char *right = wanted;
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
  if (wantedLength == 0) return false;
  for (size_t offset = 0; offset < length;) {
    size_t end = offset;
    while (end < length && bytes[end] != '\0') ++end;
    if (end - offset == wantedLength &&
        memcmp(bytes + offset, wanted, wantedLength) == 0) return true;
    offset = end < length ? end + 1 : length;
  }
  return false;
}

static bool hasProperty(IORegistryEntry *entry, const char *name)
{
  OSData *data = entry == nullptr ? nullptr
      : OSDynamicCast(OSData, entry->getProperty(name));
  return data != nullptr && data->getLength() != 0;
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

static bool matches(IORegistryEntry *entry, Subsystem subsystem)
{
  static const char *const wifiNames[] = {"icnss", "wifi", "wlan", "wcn"};
  static const char *const wifiCompat[] = {"qcom,icnss", "qcom,wcn3990", "qcom,wlan"};
  static const char *const bluetoothNames[] = {"bluetooth", "bt", "wcn3990"};
  static const char *const bluetoothCompat[] = {"qca,wcn3990", "qcom,wcn3990", "qcom,bluetooth"};
  static const char *const nfcNames[] = {"nfc", "nq", "pn5", "pn54"};
  static const char *const nfcCompat[] = {"qcom,nq-nci", "nxp,pn553", "nxp,pn54x"};
  static const char *const cameraNames[] = {"cci", "csiphy", "csid", "cam-sensor", "camera"};
  static const char *const cameraCompat[] = {"qcom,cci", "qcom,csiphy", "qcom,csid", "qcom,cam-sensor"};
  const char *const *names = nullptr;
  const char *const *compat = nullptr;
  unsigned nameCount = 0;
  unsigned compatCount = 0;
  switch (subsystem) {
    case kWifi:
      names = wifiNames; nameCount = sizeof(wifiNames) / sizeof(*wifiNames);
      compat = wifiCompat; compatCount = sizeof(wifiCompat) / sizeof(*wifiCompat);
      break;
    case kBluetooth:
      names = bluetoothNames; nameCount = sizeof(bluetoothNames) / sizeof(*bluetoothNames);
      compat = bluetoothCompat; compatCount = sizeof(bluetoothCompat) / sizeof(*bluetoothCompat);
      break;
    case kNfc:
      names = nfcNames; nameCount = sizeof(nfcNames) / sizeof(*nfcNames);
      compat = nfcCompat; compatCount = sizeof(nfcCompat) / sizeof(*nfcCompat);
      break;
    case kCamera:
      names = cameraNames; nameCount = sizeof(cameraNames) / sizeof(*cameraNames);
      compat = cameraCompat; compatCount = sizeof(cameraCompat) / sizeof(*cameraCompat);
      break;
    default:
      return false;
  }
  const char *name = entry == nullptr ? nullptr : entry->getName();
  for (unsigned i = 0; i < nameCount; ++i) {
    if (contains(name, names[i])) return true;
  }
  for (unsigned i = 0; i < compatCount; ++i) {
    if (compatibleContains(entry, compat[i])) return true;
  }
  return false;
}

static void walk(IORegistryEntry *entry, unsigned depth, unsigned *visited,
                 Fact facts[kCount])
{
  if (entry == nullptr || visited == nullptr || depth > 24 || *visited >= 4096) return;
  ++*visited;
  for (unsigned subsystem = 0; subsystem < kCount; ++subsystem) {
    if (!matches(entry, static_cast<Subsystem>(subsystem))) continue;
    Fact &fact = facts[subsystem];
    ++fact.nodes;
    fact.reg += hasProperty(entry, "reg") ? 1U : 0U;
    fact.interrupts += hasProperty(entry, "interrupts") ? 1U : 0U;
  }
  OSIterator *children = entry->getChildIterator(gIODTPlane);
  if (children == nullptr) return;
  while (IORegistryEntry *child = OSDynamicCast(IORegistryEntry, children->getNextObject())) {
    walk(child, depth + 1, visited, facts);
  }
  children->release();
}

} // namespace

class PolarisPeripheralContracts : public IOService {
  OSDeclareDefaultStructors(PolarisPeripheralContracts)

public:
  IOService *probe(IOService *provider, SInt32 *score) override
  {
    unsigned enabled = 0;
    if (provider == nullptr || !boardIsPolaris() ||
        !PE_parse_boot_argn("polaris-peripheral-probe", &enabled,
                            sizeof(enabled)) || enabled != 1) {
      return nullptr;
    }
    if (score != nullptr) *score += 20;
    return IOService::probe(provider, score);
  }

  bool start(IOService *provider) override
  {
    if (!IOService::start(provider) || !boardIsPolaris()) return false;
    unsigned visited = 0;
    Fact facts[kCount] = {};
    walk(provider, 0, &visited, facts);

    setProperty("polaris-peripheral-contract-version", 1U, 32);
    setProperty("polaris-peripheral-tree-nodes", visited, 32);
    setProperty("polaris-peripheral-chip-family", "WCN3998; DT alias WCN3990");
    setProperty("polaris-peripheral-wifi-transport-candidate", "ICNSS/SNOC + IPA/SMMU");
    setProperty("polaris-peripheral-bluetooth-transport-candidate", "Qualcomm H4 over board UART");
    setProperty("polaris-peripheral-nfc-transport-candidate", "PN54x/NCI over I2C");
    setProperty("polaris-peripheral-camera-pipeline-candidate", "CCI -> CSIPHY -> CSID -> ISP");
    setProperty("polaris-peripheral-nfc-address-candidate", 0x28U, 32);
    setProperty("polaris-peripheral-camera-sensor-candidates", "IMX363; OV5675; S5K3M3");
    setProperty("polaris-peripheral-camera-imx363-address", 0x34U, 32);
    setProperty("polaris-peripheral-camera-imx363-id-register", 0x0016U, 32);
    PolarisGeniI2cResource geniSe3 = {};
    PolarisGeniI2cResource geniSe14 = {};
    const bool geniSe3Present =
        polaris_geni_i2c_resource(PolarisGeniI2cNfc, &geniSe3) &&
        polaris_geni_i2c_resource_valid(&geniSe3);
    const bool geniSe14Present =
        polaris_geni_i2c_resource(PolarisGeniI2cTouch, &geniSe14) &&
        polaris_geni_i2c_resource_valid(&geniSe14);
    setProperty("polaris-peripheral-geni-se3-resource-valid", geniSe3Present);
    setProperty("polaris-peripheral-geni-se3-base", geniSe3.base, 64);
    setProperty("polaris-peripheral-geni-se3-size", geniSe3.size, 32);
    setProperty("polaris-peripheral-geni-se3-irq", geniSe3.irq, 32);
    setProperty("polaris-peripheral-geni-se3-address", geniSe3.address7, 32);
    setProperty("polaris-peripheral-geni-se3-irq-gpio", geniSe3.irq_gpio, 32);
    setProperty("polaris-peripheral-geni-se3-ven-gpio", geniSe3.reset_gpio, 32);
    setProperty("polaris-peripheral-geni-se3-bus", geniSe3.bus_index, 32);
    setProperty("polaris-peripheral-geni-se14-resource-valid", geniSe14Present);
    setProperty("polaris-peripheral-geni-se14-base", geniSe14.base, 64);
    setProperty("polaris-peripheral-geni-se14-size", geniSe14.size, 32);
    setProperty("polaris-peripheral-geni-se14-irq", geniSe14.irq, 32);
    setProperty("polaris-peripheral-geni-se14-address", geniSe14.address7, 32);
    setProperty("polaris-peripheral-geni-se14-irq-gpio", geniSe14.irq_gpio, 32);
    setProperty("polaris-peripheral-geni-se14-reset-gpio", geniSe14.reset_gpio, 32);
    setProperty("polaris-peripheral-geni-se14-bus", geniSe14.bus_index, 32);
    setProperty("polaris-peripheral-geni-resource-io-performed", false);
    setProperty("polaris-peripheral-wifi-firmware-candidates", "wlanmdsp.mbn; bdwlan.bin");
    setProperty("polaris-peripheral-bluetooth-firmware-candidates", "crbtfw20.tlv; crbtfw21.tlv; crnv20.bin; crnv21.bin");
    setProperty("polaris-peripheral-wlfw-bdf-chunk-bytes", PolarisWlfw::kChunkSize, 32);
    setProperty("polaris-peripheral-nci-core", true);
    setProperty("polaris-peripheral-qca-h4-core", true);
    setProperty("polaris-peripheral-cci-core", true);
    setProperty("polaris-peripheral-hardware-io", false);
    setProperty("polaris-peripheral-firmware-loaded", false);
    setProperty("polaris-peripheral-dma-created", false);
    setProperty("polaris-peripheral-network-device-published", false);
    setProperty("polaris-peripheral-camera-device-published", false);
    setProperty("polaris-peripheral-nfc-device-published", false);
    setProperty("polaris-peripheral-darwin-driver-ready", false);
    setProperty("polaris-peripheral-runtime-gates",
                "polaris-wireless-runtime=1; polaris-nfc-runtime=1; polaris-camera-runtime=1");
    setProperty("polaris-peripheral-status",
                "resource-and-protocol-contract; transport ownership required");
    setProperty("polaris-peripheral-wifi-node-count", facts[kWifi].nodes, 32);
    setProperty("polaris-peripheral-wifi-reg-count", facts[kWifi].reg, 32);
    setProperty("polaris-peripheral-wifi-interrupt-count", facts[kWifi].interrupts, 32);
    setProperty("polaris-peripheral-bluetooth-node-count", facts[kBluetooth].nodes, 32);
    setProperty("polaris-peripheral-bluetooth-reg-count", facts[kBluetooth].reg, 32);
    setProperty("polaris-peripheral-bluetooth-interrupt-count", facts[kBluetooth].interrupts, 32);
    setProperty("polaris-peripheral-nfc-node-count", facts[kNfc].nodes, 32);
    setProperty("polaris-peripheral-nfc-reg-count", facts[kNfc].reg, 32);
    setProperty("polaris-peripheral-nfc-interrupt-count", facts[kNfc].interrupts, 32);
    setProperty("polaris-peripheral-camera-node-count", facts[kCamera].nodes, 32);
    setProperty("polaris-peripheral-camera-reg-count", facts[kCamera].reg, 32);
    setProperty("polaris-peripheral-camera-interrupt-count", facts[kCamera].interrupts, 32);

    const PolarisTransportSelfTest::Result selfTest = PolarisTransportSelfTest::run();
    setProperty("polaris-peripheral-protocol-self-test-passed",
                selfTest.failed == 0 && selfTest.passed == PolarisTransportSelfTest::kAll);
    setProperty("polaris-peripheral-protocol-self-test-mask", selfTest.passed, 32);
    setProperty("polaris-peripheral-protocol-self-test-failures", selfTest.failed, 32);
    setName("PolarisPeripheralContracts");
    registerService();
    IOLog("PolarisPeripheralContracts: nodes=%u wifi=%u bt=%u nfc=%u camera=%u; I/O=0\n",
          visited, facts[kWifi].nodes, facts[kBluetooth].nodes,
          facts[kNfc].nodes, facts[kCamera].nodes);
    return true;
  }
};

OSDefineMetaClassAndStructors(PolarisPeripheralContracts, IOService)
