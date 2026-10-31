// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Polaris Darwin 23 hardware resource inventory.
//
// This file intentionally contains no MMIO, GPIO, clock, regulator, interrupt,
// firmware, DMA, I2C, SPMI, UART, UFS, or display operations.  It is the first
// Darwin-side step for the hardware listed in the Polaris WOA/DT evidence.  A
// future real driver can consume the published resource facts after its own
// transport and ownership checks are complete.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <libkern/c++/OSBoolean.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSIterator.h>
#include <pexpert/pexpert.h>
#include <string.h>

namespace {

enum Subsystem : unsigned {
  kPowerKeys = 0,
  kDisplay,
  kTouch,
  kBattery,
  kGpu,
  kWifi,
  kBluetooth,
  kNfc,
  kCamera,
  kSubsystemCount,
};

struct Fact {
  unsigned nodes = 0;
  unsigned reg = 0;
  unsigned interrupts = 0;
  unsigned clocks = 0;
  unsigned gpios = 0;
};

struct Descriptor {
  const char *name;
  const char *nodes;
  const char *reg;
  const char *interrupts;
  const char *clocks;
  const char *gpios;
  const char *state;
  const char *ready;
};

static const Descriptor kDescriptors[kSubsystemCount] = {
  {"power-keys", "polaris-power-keys-nodes", "polaris-power-keys-reg-nodes",
   "polaris-power-keys-interrupt-nodes", "polaris-power-keys-clock-nodes",
   "polaris-power-keys-gpio-nodes", "polaris-power-keys-state", "polaris-power-keys-darwin-driver-ready"},
  {"display", "polaris-display-nodes", "polaris-display-reg-nodes",
   "polaris-display-interrupt-nodes", "polaris-display-clock-nodes",
   "polaris-display-gpio-nodes", "polaris-display-state", "polaris-display-darwin-driver-ready"},
  {"touch", "polaris-touch-nodes", "polaris-touch-reg-nodes",
   "polaris-touch-interrupt-nodes", "polaris-touch-clock-nodes",
   "polaris-touch-gpio-nodes", "polaris-touch-state", "polaris-touch-darwin-driver-ready"},
  {"battery", "polaris-battery-nodes", "polaris-battery-reg-nodes",
   "polaris-battery-interrupt-nodes", "polaris-battery-clock-nodes",
   "polaris-battery-gpio-nodes", "polaris-battery-state", "polaris-battery-darwin-driver-ready"},
  {"gpu", "polaris-gpu-nodes", "polaris-gpu-reg-nodes",
   "polaris-gpu-interrupt-nodes", "polaris-gpu-clock-nodes",
   "polaris-gpu-gpio-nodes", "polaris-gpu-state", "polaris-gpu-darwin-driver-ready"},
  {"wifi", "polaris-wifi-nodes", "polaris-wifi-reg-nodes",
   "polaris-wifi-interrupt-nodes", "polaris-wifi-clock-nodes",
   "polaris-wifi-gpio-nodes", "polaris-wifi-state", "polaris-wifi-darwin-driver-ready"},
  {"bluetooth", "polaris-bluetooth-nodes", "polaris-bluetooth-reg-nodes",
   "polaris-bluetooth-interrupt-nodes", "polaris-bluetooth-clock-nodes",
   "polaris-bluetooth-gpio-nodes", "polaris-bluetooth-state", "polaris-bluetooth-darwin-driver-ready"},
  {"nfc", "polaris-nfc-nodes", "polaris-nfc-reg-nodes",
   "polaris-nfc-interrupt-nodes", "polaris-nfc-clock-nodes",
   "polaris-nfc-gpio-nodes", "polaris-nfc-state", "polaris-nfc-darwin-driver-ready"},
  {"camera", "polaris-camera-nodes", "polaris-camera-reg-nodes",
   "polaris-camera-interrupt-nodes", "polaris-camera-clock-nodes",
   "polaris-camera-gpio-nodes", "polaris-camera-state", "polaris-camera-darwin-driver-ready"},
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
  OSData *data = OSDynamicCast(OSData, entry->getProperty("compatible"));
  if (data == nullptr || wanted == nullptr) return false;
  const char *bytes = static_cast<const char *>(data->getBytesNoCopy());
  const size_t length = data->getLength();
  const size_t wantedLength = strlen(wanted);
  if (bytes == nullptr || wantedLength == 0) return false;
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
  OSData *data = OSDynamicCast(OSData, entry->getProperty(name));
  return data != nullptr && data->getLength() != 0;
}

static bool boardIsPolaris(void)
{
  IORegistryEntry *root = IORegistryEntry::fromPath("/", gIODTPlane);
  if (root == nullptr) return false;
  const bool match = compatibleContains(root, "xiaomi,polaris") &&
                     compatibleContains(root, "qcom,sdm845");
  root->release();
  return match;
}

static bool matchesAny(IORegistryEntry *entry, const char *const *names,
                       unsigned nameCount, const char *const *compatibles,
                       unsigned compatibleCount)
{
  const char *name = entry->getName();
  for (unsigned i = 0; i < nameCount; ++i) {
    if (contains(name, names[i])) return true;
  }
  for (unsigned i = 0; i < compatibleCount; ++i) {
    if (compatibleContains(entry, compatibles[i])) return true;
  }
  return false;
}

static bool matchesSubsystem(IORegistryEntry *entry, Subsystem subsystem)
{
  static const char *const keysNames[] = {"pon", "power-key", "volume", "gpio-keys", "keys"};
  static const char *const keysCompat[] = {"qcom,qpnp-power-on", "qcom,pmic-gpio", "gpio-keys"};
  static const char *const displayNames[] = {"mdss", "display", "sde"};
  static const char *const displayCompat[] = {"qcom,sde-kms", "qcom,mdss", "simple-framebuffer"};
  static const char *const touchNames[] = {"touch", "touchscreen", "synaptics", "s3330", "ft5x46", "goodix"};
  static const char *const touchCompat[] = {"synaptics,dsx-i2c-force", "synaptics", "focaltech,ft5x46", "syna", "goodix,gt9xx"};
  static const char *const batteryNames[] = {"fuel-gauge", "battery", "fg"};
  static const char *const batteryCompat[] = {"qcom,fg-gen3", "qcom,pm8998-fg", "qcom,battery"};
  static const char *const gpuNames[] = {"kgsl", "adreno", "gpu"};
  static const char *const gpuCompat[] = {"qcom,kgsl-3d0", "qcom,adreno"};
  static const char *const wifiNames[] = {"icnss", "wifi", "wlan", "wcn"};
  static const char *const wifiCompat[] = {"qcom,icnss", "qcom,wcn3990", "qcom,wlan"};
  static const char *const bluetoothNames[] = {"bluetooth", "bt", "wcn3990"};
  static const char *const bluetoothCompat[] = {"qca,wcn3990", "qcom,wcn3990", "qcom,bluetooth"};
  static const char *const nfcNames[] = {"nfc", "nq", "pn5", "pn54"};
  static const char *const nfcCompat[] = {"qcom,nq-nci", "nxp,pn553", "nxp,pn54x"};
  static const char *const cameraNames[] = {"cci", "csiphy", "csid", "cam-sensor", "camera"};
  static const char *const cameraCompat[] = {"qcom,cci", "qcom,csiphy", "qcom,csid", "qcom,cam-sensor"};
  switch (subsystem) {
    case kPowerKeys: return matchesAny(entry, keysNames, sizeof(keysNames) / sizeof(*keysNames), keysCompat, sizeof(keysCompat) / sizeof(*keysCompat));
    case kDisplay: return matchesAny(entry, displayNames, sizeof(displayNames) / sizeof(*displayNames), displayCompat, sizeof(displayCompat) / sizeof(*displayCompat));
    case kTouch: return matchesAny(entry, touchNames, sizeof(touchNames) / sizeof(*touchNames), touchCompat, sizeof(touchCompat) / sizeof(*touchCompat));
    case kBattery: return matchesAny(entry, batteryNames, sizeof(batteryNames) / sizeof(*batteryNames), batteryCompat, sizeof(batteryCompat) / sizeof(*batteryCompat));
    case kGpu: return matchesAny(entry, gpuNames, sizeof(gpuNames) / sizeof(*gpuNames), gpuCompat, sizeof(gpuCompat) / sizeof(*gpuCompat));
    case kWifi: return matchesAny(entry, wifiNames, sizeof(wifiNames) / sizeof(*wifiNames), wifiCompat, sizeof(wifiCompat) / sizeof(*wifiCompat));
    case kBluetooth: return matchesAny(entry, bluetoothNames, sizeof(bluetoothNames) / sizeof(*bluetoothNames), bluetoothCompat, sizeof(bluetoothCompat) / sizeof(*bluetoothCompat));
    case kNfc: return matchesAny(entry, nfcNames, sizeof(nfcNames) / sizeof(*nfcNames), nfcCompat, sizeof(nfcCompat) / sizeof(*nfcCompat));
    case kCamera: return matchesAny(entry, cameraNames, sizeof(cameraNames) / sizeof(*cameraNames), cameraCompat, sizeof(cameraCompat) / sizeof(*cameraCompat));
    default: return false;
  }
}

static void walk(IORegistryEntry *entry, unsigned depth, unsigned *visited,
                 Fact facts[kSubsystemCount])
{
  if (entry == nullptr || depth > 24 || *visited >= 4096) return;
  ++*visited;
  for (unsigned subsystem = 0; subsystem < kSubsystemCount; ++subsystem) {
    if (!matchesSubsystem(entry, static_cast<Subsystem>(subsystem))) continue;
    Fact &fact = facts[subsystem];
    ++fact.nodes;
    fact.reg += hasProperty(entry, "reg") ? 1U : 0U;
    fact.interrupts += hasProperty(entry, "interrupts") ? 1U : 0U;
    fact.clocks += hasProperty(entry, "clocks") ? 1U : 0U;
    fact.gpios += (hasProperty(entry, "gpios") || hasProperty(entry, "gpio")) ? 1U : 0U;
  }
  OSIterator *children = entry->getChildIterator(gIODTPlane);
  if (children == nullptr) return;
  while (IORegistryEntry *child = OSDynamicCast(IORegistryEntry, children->getNextObject())) {
    walk(child, depth + 1, visited, facts);
  }
  children->release();
}

static void publish(IOService *service, unsigned visited, const Fact facts[kSubsystemCount])
{
  service->setProperty("polaris-hw-probe-active", true);
  service->setProperty("polaris-hw-probe-mmio-performed", false);
  service->setProperty("polaris-hw-probe-writes-performed", false);
  service->setProperty("polaris-hw-probe-firmware-loaded", false);
  service->setProperty("polaris-hw-probe-dma-created", false);
  service->setProperty("polaris-hw-probe-contract-version", 1U, 32);
  service->setProperty("polaris-hw-probe-tree-nodes", visited, 32);
  for (unsigned i = 0; i < kSubsystemCount; ++i) {
    const Descriptor &d = kDescriptors[i];
    const Fact &f = facts[i];
    service->setProperty(d.nodes, f.nodes, 32);
    service->setProperty(d.reg, f.reg, 32);
    service->setProperty(d.interrupts, f.interrupts, 32);
    service->setProperty(d.clocks, f.clocks, 32);
    service->setProperty(d.gpios, f.gpios, 32);
    service->setProperty(d.state, "resource-only; no Darwin transport");
    service->setProperty(d.ready, false);
  }
}

} // namespace

class PolarisHardwareServices : public IOService {
  OSDeclareDefaultStructors(PolarisHardwareServices)
public:
  IOService *probe(IOService *provider, SInt32 *score) override {
    unsigned enabled = 0;
    if (provider == nullptr || !boardIsPolaris() ||
        !PE_parse_boot_argn("polaris-hw-probe", &enabled, sizeof(enabled)) || enabled != 1) {
      return nullptr;
    }
    if (score != nullptr) *score += 40;
    return IOService::probe(provider, score);
  }

  bool start(IOService *provider) override {
    if (!IOService::start(provider)) return false;
    unsigned visited = 0;
    Fact facts[kSubsystemCount] = {};
    walk(provider, 0, &visited, facts);
    publish(this, visited, facts);
    setName("PolarisHardwareServices");
    registerService();
    IOLog("PolarisHardwareServices: nodes=%u keys=%u display=%u touch=%u battery=%u gpu=%u wifi=%u bt=%u nfc=%u camera=%u; MMIO=0 writes=0\\n",
           visited, facts[kPowerKeys].nodes, facts[kDisplay].nodes, facts[kTouch].nodes,
           facts[kBattery].nodes, facts[kGpu].nodes, facts[kWifi].nodes,
           facts[kBluetooth].nodes, facts[kNfc].nodes, facts[kCamera].nodes);
    return true;
  }
};

OSDefineMetaClassAndStructors(PolarisHardwareServices, IOService)
