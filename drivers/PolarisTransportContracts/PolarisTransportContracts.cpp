// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Polaris transport contract service.  It compiles the protocol cores used by
// the future WCN3998, PN553, camera CCI and QUPv3 stages and publishes that
// the cores are present.  It deliberately performs no hardware I/O.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <pexpert/pexpert.h>
#include <string.h>

#include "PolarisCciProtocol.h"
#include "PolarisNci.h"
#include "PolarisProtocolSelfTest.h"
#include "PolarisQcaProtocol.h"
#include "PolarisPmicProtocol.h"
#include "PolarisWlfwProtocol.h"

extern "C" {
volatile uint32_t polaris_transport_contract_started = 0;
volatile uint32_t polaris_transport_contract_io = 0;
volatile uint32_t polaris_transport_self_test_passed = 0;
volatile uint32_t polaris_transport_self_test_failed = 0;
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

static bool boardIsPolaris()
{
  IORegistryEntry *root = IORegistryEntry::fromPath("/", gIODTPlane);
  if (root == nullptr) return false;
  const bool result = compatibleContains(root, "xiaomi,polaris") &&
                      compatibleContains(root, "qcom,sdm845");
  root->release();
  return result;
}

} // namespace

class PolarisTransportContracts : public IOService {
  OSDeclareDefaultStructors(PolarisTransportContracts)

public:
  IOService *probe(IOService *provider, SInt32 *score) override
  {
    unsigned enabled = 0;
    if (provider == nullptr || !boardIsPolaris() ||
        !PE_parse_boot_argn("polaris-transport-probe", &enabled,
                            sizeof(enabled)) || enabled != 1) {
      return nullptr;
    }
    if (score != nullptr) *score += 20;
    return IOService::probe(provider, score);
  }

  bool start(IOService *provider) override
  {
    if (!IOService::start(provider)) return false;
    setProperty("polaris-transport-contract-version", 1U, 32);
    setProperty("polaris-transport-qca-h4", true);
    setProperty("polaris-transport-wlfw-qmi", true);
    setProperty("polaris-transport-wireless-chip", "WCN3998; DT aliases WCN3990");
    setProperty("polaris-transport-wifi-firmware-candidates",
                "wlanmdsp.mbn,bdwlan.bin");
    setProperty("polaris-transport-bluetooth-firmware-candidates",
                "crbtfwXX.tlv,crnvXX.bin");
    setProperty("polaris-transport-nci-1x", true);
    setProperty("polaris-transport-camera-cci", true);
    setProperty("polaris-transport-pmic-spmi-read-only", true);
    setProperty("polaris-transport-power-keys-level-codec", true);
    setProperty("polaris-transport-fuel-gauge-codec", true);
    setProperty("polaris-transport-hardware-io", false);
    setProperty("polaris-transport-firmware-loaded", false);
    setProperty("polaris-transport-dma-created", false);
    setProperty("polaris-transport-wireless-runtime-gate",
                "polaris-wireless-runtime=1");
    setProperty("polaris-transport-darwin-driver-ready", false);
    setProperty("polaris-transport-runtime-gate", "polaris-transport-probe=1");
    const PolarisTransportSelfTest::Result selfTest = PolarisTransportSelfTest::run();
    polaris_transport_self_test_passed = selfTest.passed;
    polaris_transport_self_test_failed = selfTest.failed;
    setProperty("polaris-transport-self-test-mask", selfTest.passed, 32);
    setProperty("polaris-transport-self-test-failures", selfTest.failed, 32);
    setProperty("polaris-transport-self-test-passed",
                selfTest.failed == 0 && selfTest.passed == PolarisTransportSelfTest::kAll);
    setProperty("polaris-transport-self-test-scope",
                "QCA H4/NCI/CCI/WLFW codec vectors only; no hardware I/O");
    setName("PolarisTransportContracts");
    registerService();
    polaris_transport_contract_started = 1;
    IOLog("PolarisTransportContracts: protocol cores published; selftest=%#x failures=%#x; I/O=0\n",
          selfTest.passed, selfTest.failed);
    return true;
  }
};

OSDefineMetaClassAndStructors(PolarisTransportContracts,
                              IOService)
