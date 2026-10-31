// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Experimental read-only PM8998/PMI8998 backend for Xiaomi MIX 2S (polaris).
//
// This file is deliberately separate from PolarisPmicInput.cpp, which remains
// a metadata-only contract.  The runtime below is opt-in and only issues the
// Qualcomm PMIC-arbiter v5 observer EXT_READL command.  It never configures a
// regulator, changes GPIO direction/pull, clears an interrupt, or writes a
// charger register.  A timed-out observer lane is poisoned for the remainder
// of the boot.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/pwr_mgt/IOPMPowerSource.h>
#include <libkern/c++/OSBoolean.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSSymbol.h>
#include <libkern/c++/OSString.h>
#include <mach/kern_return.h>
#include <machine/machine_routines.h>
#include <pexpert/pexpert.h>
#include <stdint.h>
#include <string.h>

#include "../PolarisPmicInput/PolarisPmicInputProtocol.h"
#include "../PolarisTransportContracts/PolarisPmicProtocol.h"

extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);

extern "C" {
volatile uint32_t polaris_pmic_runtime_started = 0;
volatile uint32_t polaris_pmic_runtime_spmi_ready = 0;
volatile uint32_t polaris_pmic_runtime_spmi_reads = 0;
volatile uint32_t polaris_pmic_runtime_spmi_errors = 0;
volatile uint32_t polaris_pmic_runtime_key_reports = 0;
volatile uint32_t polaris_pmic_runtime_battery_samples = 0;
volatile uint32_t polaris_pmic_runtime_battery_valid = 0;
volatile uint32_t polaris_pmic_runtime_battery_revision = 0;
}

namespace {

constexpr vm_offset_t kSpmiCorePa = 0x0c440000UL;
constexpr vm_size_t kSpmiCoreSize = 0x1100UL;
constexpr vm_offset_t kSpmiConfigPa = 0x0c40a000UL;
constexpr vm_size_t kSpmiConfigSize = 0x1000UL;
constexpr vm_offset_t kSpmiObserverPa = 0x0e600000UL;
constexpr vm_size_t kSpmiObserverSize = 0x10000UL;
constexpr unsigned kSpmiMaxChannels = 512;
constexpr unsigned kSpmiTimeoutUs = 2000;
constexpr uint16_t kNoApid = 0xffff;

static vm_offset_t gCore;
static vm_offset_t gConfig;
static vm_offset_t gObserver;
static IOLock *gLock;
static uint16_t gApid[0x1000];
static bool gPoisoned[kSpmiMaxChannels];
static unsigned gChannelCount;
static bool gAttempted;
static bool gReady;

static bool boardIsPolaris()
{
  IORegistryEntry *root = IORegistryEntry::fromPath("/", gIODTPlane);
  if (root == nullptr) return false;
  OSData *data = OSDynamicCast(OSData, root->getProperty("compatible"));
  bool polaris = false;
  bool sdm845 = false;
  if (data != nullptr && data->getBytesNoCopy() != nullptr) {
    const uint8_t *bytes = static_cast<const uint8_t *>(data->getBytesNoCopy());
    const size_t length = data->getLength();
    for (size_t offset = 0; offset < length;) {
      size_t end = offset;
      while (end < length && bytes[end] != 0) ++end;
      const size_t n = end - offset;
      polaris |= n == strlen("xiaomi,polaris") &&
                 memcmp(bytes + offset, "xiaomi,polaris", n) == 0;
      sdm845 |= n == strlen("qcom,sdm845") &&
                memcmp(bytes + offset, "qcom,sdm845", n) == 0;
      offset = end < length ? end + 1 : length;
    }
  }
  root->release();
  return polaris && sdm845;
}

static uint32_t read32(vm_offset_t base, unsigned offset)
{
  uint32_t value = *(volatile uint32_t *)(base + offset);
  __asm__ volatile("dmb oshld" ::: "memory");
  return value;
}

static uint16_t findApid(uint16_t peripheral)
{
  uint16_t found = kNoApid;
  for (unsigned i = 0; i < gChannelCount; ++i) {
    const uint32_t mapping = read32(gCore, 0x900U + 4U * i);
    if (mapping == 0 || ((mapping >> 8) & 0xfffU) != peripheral) continue;
    const uint32_t owner = read32(gConfig, 0x700U + 4U * i) & 7U;
    if (found == kNoApid || owner == 0) found = static_cast<uint16_t>(i);
  }
  return found;
}

static bool bootArg(const char *name)
{
  unsigned value = 0;
  return name != nullptr && PE_parse_boot_argn(name, &value, sizeof(value)) &&
         value == 1;
}

static bool spmiInit()
{
  if (!boardIsPolaris()) return false;
  if (gAttempted) return gReady;
  gAttempted = true;
  gLock = IOLockAlloc();
  if (gLock == nullptr) return false;
  gCore = ml_io_map(kSpmiCorePa, kSpmiCoreSize);
  gConfig = ml_io_map(kSpmiConfigPa, kSpmiConfigSize);
  gObserver = ml_io_map(kSpmiObserverPa, kSpmiObserverSize);
  if (gCore == 0 || gConfig == 0 || gObserver == 0) {
    IOLog("POLARIS PMIC: SPMI MMIO mapping failed\n");
    return false;
  }
  const uint32_t version = read32(gCore, 0);
  // v5 core resources expose channel descriptors at 0x900..0x10fc.
  gChannelCount = (kSpmiCoreSize - 0x900U) / 4U;
  if (version < 0x50000000U || version >= 0x70000000U ||
      gChannelCount == 0 || gChannelCount > kSpmiMaxChannels) {
    IOLog("POLARIS PMIC: unsupported SPMI version=%#x channels=%u\n",
          version, gChannelCount);
    return false;
  }
  for (unsigned i = 0; i < sizeof(gApid) / sizeof(gApid[0]); ++i)
    gApid[i] = kNoApid;
  memset(gPoisoned, 0, sizeof(gPoisoned));
  gReady = true;
  polaris_pmic_runtime_spmi_ready = 1;
  IOLog("POLARIS PMIC: SPMI observer v5 version=%#x channels=%u\n",
        version, gChannelCount);
  return true;
}

static bool spmiRead(uint16_t peripheral, uint8_t reg, uint8_t *out,
                     unsigned count)
{
  if (!gReady || gLock == nullptr || out == nullptr ||
      !PolarisPmicInput::allowRead(peripheral, reg, count)) {
    polaris_pmic_runtime_spmi_errors = polaris_pmic_runtime_spmi_errors + 1;
    return false;
  }
  IOLockLock(gLock);
  uint16_t apid = gApid[peripheral];
  if (apid == kNoApid) {
    apid = findApid(peripheral);
    gApid[peripheral] = apid;
  }
  if (apid == kNoApid || apid >= kSpmiMaxChannels || gPoisoned[apid]) {
    IOLockUnlock(gLock);
    polaris_pmic_runtime_spmi_errors = polaris_pmic_runtime_spmi_errors + 1;
    return false;
  }
  const unsigned lane = 0x80U * apid;
  const uint32_t command = (1U << 27) |
      (static_cast<uint32_t>(reg) << 4) | (count - 1U);
  __asm__ volatile("dmb oshst" ::: "memory");
  *(volatile uint32_t *)(gObserver + lane) = command;
  __asm__ volatile("dsb osh" ::: "memory");
  uint32_t status = 0;
  for (unsigned waited = 0; waited < kSpmiTimeoutUs; ++waited) {
    status = read32(gObserver, lane + 0x08U);
    if (status & 1U) break;
    IODelay(1);
  }
  if (!(status & 1U) || (status & 0x0eU)) {
    if (!(status & 1U)) {
      gPoisoned[apid] = true;
      IOLog("POLARIS PMIC: observer timeout peripheral=%#x apid=%u\n",
            peripheral, apid);
    }
    IOLockUnlock(gLock);
    polaris_pmic_runtime_spmi_errors = polaris_pmic_runtime_spmi_errors + 1;
    return false;
  }
  const uint32_t data0 = read32(gObserver, lane + 0x18U);
  const uint32_t data1 = count > 4 ? read32(gObserver, lane + 0x1cU) : 0;
  for (unsigned i = 0; i < count; ++i)
    out[i] = static_cast<uint8_t>((i < 4 ? data0 : data1) >> (8U * (i & 3U)));
  IOLockUnlock(gLock);
  polaris_pmic_runtime_spmi_reads = polaris_pmic_runtime_spmi_reads + 1;
  return true;
}

static bool readByte(uint16_t peripheral, uint8_t reg, uint8_t *out)
{
  return spmiRead(peripheral, reg, out, 1);
}

static void publishString(IOService *service, const char *key, const char *value)
{
  if (service == nullptr || key == nullptr || value == nullptr) return;
  OSString *string = OSString::withCString(value);
  if (string != nullptr) {
    service->setProperty(key, string);
    string->release();
  }
}

static void publishNumber(IOService *service, const char *key, uint64_t value)
{
  if (service == nullptr || key == nullptr) return;
  OSNumber *number = OSNumber::withNumber(value, 64);
  if (number != nullptr) {
    service->setProperty(key, number);
    number->release();
  }
}

using ButtonSink = void (*)(void *, uint32_t);
static ButtonSink gButtonSink;
static void *gButtonSinkContext;

static void publishKeys(IOService *service, uint32_t mask)
{
  publishNumber(service, "PolarisButtonMask", mask);
  polaris_pmic_runtime_key_reports = polaris_pmic_runtime_key_reports + 1;
  if (gButtonSink != nullptr) gButtonSink(gButtonSinkContext, mask);
}

} // namespace

extern "C" void polaris_buttons_set_sink(ButtonSink sink, void *context)
{
  gButtonSinkContext = context;
  __asm__ volatile("dmb ish" ::: "memory");
  gButtonSink = sink;
}

class PolarisKeysRuntime : public IOService {
  OSDeclareDefaultStructors(PolarisKeysRuntime)
  IOWorkLoop *loop_ = nullptr;
  IOTimerEventSource *timer_ = nullptr;
  bool running_ = false;
  bool pon_ = false;
  bool gpio_ = false;
  uint32_t lastMask_ = 0;
  bool candidate_[3] = {};
  bool candidateValid_[3] = {};
  bool live_[3] = {};
  bool down_[3] = {};

  static constexpr uint32_t keyBit(unsigned index)
  {
    return index < 3 ? (1U << (index + 1U)) : 0;
  }

  void publishStableMask()
  {
    uint32_t mask = 0;
    for (unsigned i = 0; i < 3; ++i) {
      if (down_[i]) mask |= keyBit(i);
    }
    if (mask != lastMask_) {
      lastMask_ = mask;
      publishKeys(this, mask);
    }
  }

  void disableKey(unsigned index)
  {
    if (index >= 3) return;
    candidateValid_[index] = false;
    live_[index] = false;
    down_[index] = false;
    publishStableMask();
  }

  void updateKey(unsigned index, bool pressed)
  {
    if (index >= 3) return;
    // Require two identical samples and observe an initial released state
    // before trusting a transition. This prevents a held key during boot from
    // being reported as a synthetic press and mirrors the old Polaris chain's
    // debounce contract.
    if (!candidateValid_[index] || candidate_[index] != pressed) {
      candidate_[index] = pressed;
      candidateValid_[index] = true;
      return;
    }
    if (!live_[index]) {
      if (!pressed) live_[index] = true;
      return;
    }
    if (down_[index] == pressed) return;
    down_[index] = pressed;
    publishStableMask();
  }

  void poll()
  {
    uint8_t pon = 0, gpio = 0;
    if (pon_) {
      if (readByte(0x008, 0x10, &pon)) {
        updateKey(0, (pon & 0x01U) != 0); // consumer power
        updateKey(2, (pon & 0x02U) != 0); // volume down
      } else {
        pon_ = false;
        disableKey(0);
        disableKey(2);
      }
    }
    if (gpio_) {
      if (readByte(0x0c5, 0x10, &gpio)) {
        updateKey(1, (gpio & 0x01U) == 0); // volume up, active-low
      } else {
        gpio_ = false;
        disableKey(1);
      }
    }
    if (!pon_ && !gpio_) running_ = false;
  }

  static void timerFired(OSObject *owner, IOTimerEventSource *sender)
  {
    auto *self = OSDynamicCast(PolarisKeysRuntime, owner);
    if (self != nullptr && self->running_) {
      self->poll();
      if (self->running_) sender->setTimeoutMS(16);
    }
  }

public:
  bool start(IOService *provider) override
  {
    if (!IOService::start(provider) || !boardIsPolaris() ||
        !bootArg("polariskeys")) return false;
    if (!spmiInit()) return false;
    uint8_t type = 0, subtype = 0, mode = 0, pull = 0, enable = 0;
    pon_ = readByte(0x008, 0x04, &type) && readByte(0x008, 0x05, &subtype) &&
           subtype >= 1 && subtype <= 5;
    const bool gpioIdentity = readByte(0x0c5, 0x04, &type) &&
        readByte(0x0c5, 0x05, &subtype) && readByte(0x0c5, 0x40, &mode) &&
        readByte(0x0c5, 0x42, &pull) && readByte(0x0c5, 0x46, &enable);
    gpio_ = gpioIdentity && type == 0x10 &&
            (subtype == 0x10 || subtype == 0x11) && (mode & 3U) == 0 &&
            (pull & 7U) < 4 && (enable & 0x80U);
    if (!pon_ && !gpio_) return false;
    setProperty("PolarisDriverKind", "Keys");
    setProperty("PolarisDriverState", "experimental read-only SPMI polling");
    setProperty("HardwareWritesEnabled", kOSBooleanFalse);
    setProperty("DeviceOperations", "SPMI observer reads; optional HID sink");
    publishString(this, "PowerKeySource", "PM8998 SID0 PON 0x08 KPDPWR_N");
    publishString(this, "VolumeDownSource", "PM8998 SID0 PON 0x08 RESIN_N");
    publishString(this, "VolumeUpSource", "PM8998 SID0 GPIO6 0xc5 active-low");
    publishNumber(this, "PolarisKeysPONUsable", pon_ ? 1 : 0);
    publishNumber(this, "PolarisKeysGPIOUsable", gpio_ ? 1 : 0);
    loop_ = IOWorkLoop::workLoop();
    timer_ = loop_ != nullptr ? IOTimerEventSource::timerEventSource(this, &timerFired) : nullptr;
    if (loop_ == nullptr || timer_ == nullptr ||
        loop_->addEventSource(timer_) != kIOReturnSuccess) {
      OSSafeReleaseNULL(timer_);
      OSSafeReleaseNULL(loop_);
      return false;
    }
    running_ = true;
    setName("PolarisKeysRuntime");
    registerService();
    timer_->setTimeoutMS(16);
    return true;
  }

  void stop(IOService *provider) override
  {
    running_ = false;
    if (timer_ != nullptr) timer_->cancelTimeout();
    if (loop_ != nullptr && timer_ != nullptr) loop_->removeEventSource(timer_);
    IOService::stop(provider);
  }

  void free() override
  {
    OSSafeReleaseNULL(timer_);
    OSSafeReleaseNULL(loop_);
    IOService::free();
  }
};

OSDefineMetaClassAndStructors(PolarisKeysRuntime, IOService)

namespace {

static bool readStable(uint16_t peripheral, uint8_t reg, uint8_t out[2])
{
  uint8_t first[2] = {}, second[2] = {};
  for (unsigned attempt = 0; attempt < 4; ++attempt) {
    if (!spmiRead(peripheral, reg, first, 2) ||
        !spmiRead(peripheral, reg, second, 2)) return false;
    if (first[0] == second[0] && first[1] == second[1]) {
      out[0] = first[0]; out[1] = first[1]; return true;
    }
  }
  return false;
}

} // namespace

class PolarisBatteryRuntime : public IOPMPowerSource {
  OSDeclareDefaultStructors(PolarisBatteryRuntime)
  IOWorkLoop *loop_ = nullptr;
  IOTimerEventSource *timer_ = nullptr;
  PolarisPmicInput::Revision revision_ = PolarisPmicInput::kUnknown;
  bool running_ = false;
  bool real_ = false;

  void putBool(const char *key, bool value)
  {
    const OSSymbol *symbol = OSSymbol::withCString(key);
    if (symbol != nullptr) setPSProperty(symbol, value ? kOSBooleanTrue : kOSBooleanFalse);
    OSSafeReleaseNULL(symbol);
  }

  void putNumber(const char *key, uint64_t value)
  {
    const OSSymbol *symbol = OSSymbol::withCString(key);
    OSNumber *number = OSNumber::withNumber(value, 64);
    if (symbol != nullptr && number != nullptr) setPSProperty(symbol, number);
    OSSafeReleaseNULL(number);
    OSSafeReleaseNULL(symbol);
  }

  void publishUnknown()
  {
    setBatteryInstalled(false);
    setCurrentCapacity(0);
    setMaxCapacity(0);
    setExternalConnected(false);
    setExternalChargeCapable(false);
    setIsCharging(false);
    setAtWarnLevel(false);
    setAtCriticalLevel(false);
    setVoltage(0);
    setAmperage(0);
    setTimeRemaining(-1);
    setCycleCount(0);
    putBool("PolarisBatteryHardwareSampleValid", false);
    putBool("PolarisBatteryCurrentValid", false);
    putBool("PolarisBatteryChargerStatusValid", false);
    putNumber("PolarisBatteryPercent", 0);
    updateStatus();
  }

  void poll()
  {
    polaris_pmic_runtime_battery_samples = polaris_pmic_runtime_battery_samples + 1;
    PolarisPmicInput::ObserverSnapshot snapshot = {};
    uint8_t revid[3] = {}, revid2[3] = {};
    PolarisPmicInput::Revision revision = PolarisPmicInput::kUnknown;
    if (spmiRead(0x201, 0x03, revid, 3) &&
        spmiRead(0x201, 0x03, revid2, 3)) {
      revision = PolarisPmicInput::identifyRevision(revid, revid2);
    }
    if (revision == PolarisPmicInput::kUnknown) {
      publishUnknown();
      return;
    }
    revision_ = revision;
    polaris_pmic_runtime_battery_revision = revid[0];
    snapshot.revision = revision;
    uint8_t soc[2] = {}, voltage[2] = {}, current[2] = {}, temp[2] = {};
    uint8_t socSubtype = 0, infoSubtype = 0;
    if (!readByte(0x240, 0x05, &socSubtype) || socSubtype != 0x10 ||
        !readByte(0x241, 0x05, &infoSubtype) || infoSubtype != 0x11 ||
        !spmiRead(0x240, 0x09, soc, 2) || soc[0] != soc[1] ||
        !readStable(0x241, 0xa0, voltage) ||
        !readStable(0x241, 0xa2, current) ||
        !readStable(0x241, 0x50, temp)) {
      publishUnknown();
      return;
    }
    snapshot.soc = soc[0];
    snapshot.voltage0 = voltage[0]; snapshot.voltage1 = voltage[1];
    snapshot.current0 = current[0]; snapshot.current1 = current[1];
    snapshot.temperature0 = temp[0]; snapshot.temperature1 = temp[1];
    PolarisPmicInput::BatterySample sample = {};
    if (!PolarisPmicInput::decodeBattery(snapshot, &sample) ||
        sample.millivolts < 2800 || sample.millivolts > 4600 ||
        sample.temperatureDeciCelsius < -400 || sample.temperatureDeciCelsius > 900) {
      publishUnknown();
      return;
    }
    setBatteryInstalled(true);
    // IOPMPowerSource defines these fields in mAh. Keep the percentage as a
    // separate property for clients that want the display value.
    const unsigned capacityMah = (3400U * sample.percent + 50U) / 100U;
    setCurrentCapacity(capacityMah);
    setMaxCapacity(3400);
    setExternalConnected(false);
    setExternalChargeCapable(false);
    setIsCharging(false);
    setAtWarnLevel(false);
    setAtCriticalLevel(false);
    setVoltage(sample.millivolts);
    setAmperage(-sample.currentMicroamps / 1000);
    setTimeRemaining(-1);
    setCycleCount(0);
    putBool("FullyCharged", sample.percent >= 100);
    putBool("PolarisBatteryHardwareSampleValid", true);
    putBool("PolarisBatteryCurrentValid", true);
    putBool("PolarisBatteryChargerStatusValid", false);
    putNumber("PolarisBatteryPercent", sample.percent);
    putNumber("DesignCapacity", 3400);
    putNumber("NominalChargeCapacity", 3400);
    putNumber("AppleRawCurrentCapacity",
              (3400U * sample.percent + 50U) / 100U);
    putNumber("AppleRawMaxCapacity", 3400);
    putNumber("Temperature", static_cast<uint64_t>(sample.temperatureDeciCelsius * 10));
  polaris_pmic_runtime_battery_valid = polaris_pmic_runtime_battery_valid + 1;
    updateStatus();
  }

  static void timerFired(OSObject *owner, IOTimerEventSource *sender)
  {
    auto *self = OSDynamicCast(PolarisBatteryRuntime, owner);
    if (self != nullptr && self->running_) {
      self->poll();
      if (self->running_) sender->setTimeoutMS(30000);
    }
  }

public:
  bool start(IOService *provider) override
  {
    if (!IOPMPowerSource::start(provider) || !boardIsPolaris() ||
        !bootArg("polarisbattery")) return false;
    if (!spmiInit()) return false;
    publishUnknown();
    loop_ = IOWorkLoop::workLoop();
    timer_ = loop_ != nullptr ? IOTimerEventSource::timerEventSource(this, &timerFired) : nullptr;
    if (loop_ == nullptr || timer_ == nullptr ||
        loop_->addEventSource(timer_) != kIOReturnSuccess) {
      OSSafeReleaseNULL(timer_);
      OSSafeReleaseNULL(loop_);
      return false;
    }
    real_ = true;
    running_ = true;
    setProperty("PolarisDriverKind", "Battery");
    setProperty("PolarisDriverState", "experimental read-only SPMI fuel gauge");
    setProperty("HardwareWritesEnabled", kOSBooleanFalse);
    setProperty("DeviceOperations", "SPMI observer reads only");
    publishString(this, "FuelGauge", "PMI8998 qcom,fg-gen3 candidate");
    setName("PolarisBatteryRuntime");
    registerService();
    poll();
    timer_->setTimeoutMS(30000);
    return true;
  }

  void stop(IOService *provider) override
  {
    running_ = false;
    if (timer_ != nullptr) timer_->cancelTimeout();
    if (loop_ != nullptr && timer_ != nullptr) loop_->removeEventSource(timer_);
    IOPMPowerSource::stop(provider);
  }

  void free() override
  {
    OSSafeReleaseNULL(timer_);
    OSSafeReleaseNULL(loop_);
    IOPMPowerSource::free();
  }
};

OSDefineMetaClassAndStructors(PolarisBatteryRuntime, IOPMPowerSource)

extern "C" void polaris_pmic_runtime_static_init(void)
    __asm__("__GLOBAL__sub_I_PolarisPmicRuntime.cpp");
