// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Darwin 23 Polaris Synaptics touch contract and opt-in runtime launcher.
// The normal personality is contract-only.  The arm-io personality is used
// only for the separately gated GPIO33/GPIO34 transport in PolarisTouchRuntime.c.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <libkern/c++/OSData.h>
#include <pexpert/pexpert.h>
#include <string.h>

#include "SynapticsRmi4Protocol.h"

extern "C" int polaris_touch_runtime_start(void);
extern "C" volatile uint32_t polaris_touch_runtime_state[8];
extern "C" volatile uint32_t polaris_touch_count;
extern "C" volatile uint32_t polaris_touch_hid_reports;

extern "C" {
volatile uint32_t polaris_rmi4_touch_probe_calls = 0;
volatile uint32_t polaris_rmi4_touch_contract_published = 0;
volatile uint32_t polaris_rmi4_touch_i2c_transactions = 0;
volatile uint32_t polaris_rmi4_touch_hid_registered = 0;
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

static bool polarisBoard(void)
{
  IORegistryEntry *root = IORegistryEntry::fromPath("/", gIODTPlane);
  if (root == nullptr) return false;
  const bool match = compatibleContains(root, "xiaomi,polaris") &&
                     compatibleContains(root, "qcom,sdm845");
  root->release();
  return match;
}

static bool synapticsCandidate(IOService *provider)
{
  if (provider == nullptr || !compatibleContains(provider, "synaptics,dsx-i2c-force")) {
    return false;
  }
  /* A candidate DT node without bus/interrupt resources is not safe to claim.
   * We do not decode or trust their values here; a later transport must do so
   * with an ABI-specific QUPv3 provider. */
  return hasProperty(provider, "reg") && hasProperty(provider, "interrupts");
}

static bool armIoProvider(IOService *provider)
{
  const char *name = provider != nullptr ? provider->getName() : nullptr;
  return name != nullptr && strcmp(name, "arm-io") == 0;
}

} // namespace

class PolarisSynapticsTouch : public IOService {
  OSDeclareDefaultStructors(PolarisSynapticsTouch)
  uint32_t stage_ = 0;

public:
  IOService *probe(IOService *provider, SInt32 *score) override
  {
    ++polaris_rmi4_touch_probe_calls;
    unsigned stage = 0;
    unsigned runtime = 0;
    const bool runtimeRequested =
        PE_parse_boot_argn("polaris-touch-runtime", &runtime, sizeof(runtime)) &&
        runtime == 1;
    if (provider == nullptr || !polarisBoard() ||
        !PE_parse_boot_argn("polaris-rmi4-touch", &stage, sizeof(stage)) ||
        (stage != 1 && stage != 2) ||
        !(synapticsCandidate(provider) ||
          (stage == 2 && runtimeRequested && armIoProvider(provider)))) {
      return nullptr;
    }
    stage_ = stage;
    if (score != nullptr) *score += 30;
    return IOService::probe(provider, score);
  }

  bool start(IOService *provider) override
  {
    if (!IOService::start(provider)) return false;
    setProperty("polaris-rmi4-touch-contract-version", 1U, 32);
    setProperty("polaris-rmi4-touch-stage", stage_, 32);
    setProperty("polaris-rmi4-touch-bus", "gpio33_gpio34_bitbang_i2c");
    setProperty("polaris-rmi4-touch-compatible", "synaptics,dsx-i2c-force");
    setProperty("polaris-rmi4-touch-address", 0x20U, 32);
    setProperty("polaris-rmi4-touch-irq-gpio", 125U, 32);
    setProperty("polaris-rmi4-touch-reset-gpio", 99U, 32);
    setProperty("polaris-rmi4-touch-panel-width", 1080U, 32);
    setProperty("polaris-rmi4-touch-panel-height", 2160U, 32);
    setProperty("polaris-rmi4-touch-protocol", "RMI4 F01/F12; bounded RMI4/F12 frame parser");
    setProperty("polaris-rmi4-touch-transport-state",
                "contract-only; GPIO runtime is explicit and experimental");
    setProperty("polaris-rmi4-touch-pdt-read", false);
    setProperty("polaris-rmi4-touch-reset-performed", false);
    setProperty("polaris-rmi4-touch-mmio-performed", false);
    setProperty("polaris-rmi4-touch-i2c-transactions", 0U, 32);
    setProperty("polaris-rmi4-touch-hid-registered", false);
    setProperty("polaris-rmi4-touch-runtime-gate", "polaris-touch-runtime=1");
    setProperty("polaris-rmi4-touch-runtime-transport", "GPIO33/GPIO34 open-drain RMI4");
    setProperty("polaris-rmi4-touch-runtime-mmio", false);
    setProperty("polaris-rmi4-touch-runtime-state", 0U, 32);
    setProperty("polaris-rmi4-touch-runtime-slots", 0U, 32);
    setProperty("polaris-rmi4-touch-runtime-reports", 0U, 32);
    setProperty("polaris-rmi4-touch-darwin-driver-ready", false);
    unsigned runtime = 0;
    const bool runtimeRequested =
        PE_parse_boot_argn("polaris-touch-runtime", &runtime, sizeof(runtime)) &&
        runtime == 1;
    if (stage_ == 2 && runtimeRequested) {
      const int started = polaris_touch_runtime_start();
      setProperty("polaris-rmi4-touch-runtime-started", started != 0);
      setProperty("polaris-rmi4-touch-runtime-state",
                  polaris_touch_runtime_state[0], 32);
      setProperty("polaris-rmi4-touch-runtime-slots",
                  polaris_touch_runtime_state[2], 32);
      setProperty("polaris-rmi4-touch-runtime-reports",
                  polaris_touch_hid_reports, 32);
      setProperty("polaris-rmi4-touch-darwin-driver-ready", false);
    } else {
      setProperty("polaris-rmi4-touch-runtime-started", false);
    }
    setName("PolarisSynapticsTouch");
    registerService();
    polaris_rmi4_touch_contract_published = 1;
    IOLog("PolarisSynapticsTouch: stage=%u bus=GPIO33/34 addr=0x20; runtime=%s\n",
          stage_, runtimeRequested ? "requested" : "off");
    return true;
  }
};

OSDefineMetaClassAndStructors(PolarisSynapticsTouch, IOService)

