// SPDX-License-Identifier: BSD-2-Clause-Patent
// Explicit source-kernel start path for the board-gated Polaris services.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSMetaClass.h>
#include <libkern/c++/OSObject.h>
#include <pexpert/pexpert.h>
#include <mach/kmod.h>
#include <string.h>

extern "C" kmod_info_t g_kernel_kmod_info;

extern "C" void polaris_board_probe_static_init(void)
    __asm__("__GLOBAL__sub_I_PolarisBoardProbe.cpp");
extern "C" void polaris_hardware_services_static_init(void)
    __asm__("__GLOBAL__sub_I_PolarisHardwareServices.cpp");
extern "C" void polaris_pmic_input_static_init(void)
    __asm__("__GLOBAL__sub_I_PolarisPmicInput.cpp");
extern "C" void polaris_pmic_runtime_static_init(void)
    __asm__("__GLOBAL__sub_I_PolarisPmicRuntime.cpp");
extern "C" void polaris_synaptics_touch_static_init(void)
    __asm__("__GLOBAL__sub_I_PolarisSynapticsTouch.cpp");
extern "C" void polaris_transport_contracts_static_init(void)
    __asm__("__GLOBAL__sub_I_PolarisTransportContracts.cpp");
extern "C" void polaris_peripheral_contracts_static_init(void)
    __asm__("__GLOBAL__sub_I_PolarisPeripheralContracts.cpp");
extern "C" void polaris_nfc_contract_static_init(void)
    __asm__("__GLOBAL__sub_I_PolarisNfcContract.cpp");
extern "C" void polaris_camera_contract_static_init(void)
    __asm__("__GLOBAL__sub_I_PolarisCameraContract.cpp");
extern "C" void polaris_display_contract_static_init(void)
    __asm__("__GLOBAL__sub_I_PolarisDisplayContract.cpp");
extern "C" void polaris_a630_probe_static_init(void)
    __asm__("__GLOBAL__sub_I_PolarisA630Probe.cpp");
// The iPadOS-stage HID bridge is built only when XNU_POLARIS_HID_INPUT is
// selected. Keep this weak so the ordinary source-kernel profile does not
// acquire an unresolved dependency on the private IOHID ABI.
extern "C" void polaris_hid_touch_start(void) __attribute__((weak_import));

extern "C" {
volatile uint32_t polaris_runtime_started = 0;
volatile uint32_t polaris_runtime_services_started = 0;
volatile uint32_t polaris_runtime_services_failed = 0;
}

namespace {

static bool gMetaInitialized = false;

static bool boardIsPolaris(void)
{
  IORegistryEntry *root = IORegistryEntry::fromPath("/", gIODTPlane);
  if (root == nullptr) return false;
  OSData *data = OSDynamicCast(OSData, root->getProperty("compatible"));
  bool polaris = false;
  bool sdm845 = false;
  if (data != nullptr && data->getBytesNoCopy() != nullptr) {
    const char *bytes = static_cast<const char *>(data->getBytesNoCopy());
    const size_t length = data->getLength();
    for (size_t offset = 0; offset < length;) {
      size_t end = offset;
      while (end < length && bytes[end] != '\0') ++end;
      const size_t itemLength = end - offset;
      polaris |= itemLength == strlen("xiaomi,polaris") &&
                 memcmp(bytes + offset, "xiaomi,polaris", itemLength) == 0;
      sdm845 |= itemLength == strlen("qcom,sdm845") &&
                memcmp(bytes + offset, "qcom,sdm845", itemLength) == 0;
      offset = end < length ? end + 1 : length;
    }
  }
  root->release();
  return polaris && sdm845;
}

static bool initLinkedClasses(void)
{
  if (gMetaInitialized) return true;
  void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
  if (handle == nullptr) return false;
  polaris_board_probe_static_init();
  polaris_hardware_services_static_init();
  polaris_pmic_input_static_init();
  polaris_pmic_runtime_static_init();
  polaris_synaptics_touch_static_init();
  polaris_transport_contracts_static_init();
  polaris_peripheral_contracts_static_init();
  polaris_nfc_contract_static_init();
  polaris_camera_contract_static_init();
  polaris_display_contract_static_init();
  polaris_a630_probe_static_init();
  if (OSMetaClass::postModLoad(handle) != kOSReturnSuccess) return false;
  gMetaInitialized = true;
  return true;
}

static IOService *findArmIo(IOService *fallback)
{
  OSDictionary *matching = IOService::nameMatching("arm-io");
  IOService *armIo = matching != nullptr
      ? IOService::waitForMatchingService(matching, 1000000ULL) : nullptr;
  OSSafeReleaseNULL(matching);
  return armIo != nullptr ? armIo : fallback;
}

static bool startService(const char *className, IOService *provider)
{
  if (className == nullptr || provider == nullptr) return false;
  OSObject *object = OSMetaClass::allocClassWithName(className);
  IOService *service = OSDynamicCast(IOService, object);
  if (service == nullptr || !service->init() || !service->attach(provider) ||
      !service->start(provider)) {
    if (service != nullptr) {
      if (service->getProvider() == provider) service->detach(provider);
      service->release();
    } else if (object != nullptr) {
      object->release();
    }
    polaris_runtime_services_failed = polaris_runtime_services_failed + 1;
    return false;
  }
  service->registerService(kIOServiceSynchronous);
  service->release();
  polaris_runtime_services_started = polaris_runtime_services_started + 1;
  return true;
}

static bool bootArgEnabled(const char *name)
{
  unsigned enabled = 0;
  return name != nullptr &&
         PE_parse_boot_argn(name, &enabled, sizeof(enabled)) && enabled == 1;
}

} // namespace

extern "C" void polaris_runtime_start(IOService *platform)
{
  unsigned enabled = 0;
  if (!PE_parse_boot_argn("polaris-runtime", &enabled, sizeof(enabled)) ||
      enabled != 1 || polaris_runtime_started != 0 || !boardIsPolaris()) {
    return;
  }
  polaris_runtime_started = 1;
  if (!initLinkedClasses()) {
    polaris_runtime_services_failed = polaris_runtime_services_failed + 1;
    return;
  }
  IOService *platformService = platform != nullptr ? platform : IOService::getPlatform();
  IOService *provider = findArmIo(platformService);
  if (provider == nullptr) {
    polaris_runtime_services_failed = polaris_runtime_services_failed + 1;
    return;
  }
  static const char *const classes[] = {
      "PolarisBoardProbe", "PolarisHardwareServices", "PolarisPmicInput",
      "PolarisSynapticsTouch", "PolarisTransportContracts", "PolarisA630Probe",
  };
  for (const char *className : classes) (void)startService(className, provider);
  unsigned optional = 0;
  if (PE_parse_boot_argn("polariskeys", &optional, sizeof(optional)) && optional == 1)
    (void)startService("PolarisKeysRuntime", provider);
  optional = 0;
  if (PE_parse_boot_argn("polarisbattery", &optional, sizeof(optional)) && optional == 1)
    (void)startService("PolarisBatteryRuntime", provider);
  optional = 0;
  if (PE_parse_boot_argn("polaris-peripheral-probe", &optional, sizeof(optional)) && optional == 1)
    (void)startService("PolarisPeripheralContracts", provider);
  if (bootArgEnabled("polaris-nfc-probe"))
    (void)startService("PolarisNfcContract", provider);
  if (bootArgEnabled("polaris-camera-probe"))
    (void)startService("PolarisCameraContract", provider);
  if (bootArgEnabled("polaris-display-probe"))
    (void)startService("PolarisDisplayContract", provider);
  if (&polaris_hid_touch_start) polaris_hid_touch_start();
  if (provider != platformService) provider->release();
  IOLog("PolarisRuntime: started=%u failed=%u\n",
        polaris_runtime_services_started, polaris_runtime_services_failed);
}
