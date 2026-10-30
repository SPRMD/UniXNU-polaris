// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Polaris Adreno 630 resource contract.  This service is intentionally
// read-only at the device-tree level.  A real GPU backend must separately
// prove ownership of GPUCC/GDSC/PAS13/GMU/SMMU before it can touch hardware.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <libkern/c++/OSBoolean.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSNumber.h>
#include <pexpert/pexpert.h>
#include <stdint.h>
#include <string.h>

namespace {

struct Range {
  uint64_t address;
  uint64_t size;
};

static bool compatibleContains(IORegistryEntry *entry, const char *wanted)
{
  if (entry == nullptr || wanted == nullptr) return false;
  OSData *data = OSDynamicCast(OSData, entry->getProperty("compatible"));
  if (data == nullptr || data->getBytesNoCopy() == nullptr) return false;
  const uint8_t *bytes = static_cast<const uint8_t *>(data->getBytesNoCopy());
  const size_t length = data->getLength();
  const size_t wantedLength = strlen(wanted);
  if (wantedLength == 0) return false;
  for (size_t offset = 0; offset < length;) {
    size_t end = offset;
    while (end < length && bytes[end] != 0) ++end;
    if (end - offset == wantedLength &&
        memcmp(bytes + offset, wanted, wantedLength) == 0) return true;
    offset = end < length ? end + 1 : length;
  }
  return false;
}

static uint32_t be32(const uint8_t *p)
{
  return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) |
         (uint32_t(p[2]) << 8) | uint32_t(p[3]);
}

static unsigned readRanges(IORegistryEntry *entry, Range *out, unsigned capacity)
{
  if (entry == nullptr || out == nullptr || capacity == 0) return 0;
  OSData *data = OSDynamicCast(OSData, entry->getProperty("reg"));
  if (data == nullptr || data->getBytesNoCopy() == nullptr) return 0;
  const uint8_t *bytes = static_cast<const uint8_t *>(data->getBytesNoCopy());
  const size_t length = data->getLength();
  /* The checked Polaris DT inventory uses 32-bit address/size cells.  Accept
   * the common 8-byte and 16-byte encodings but reject partial cells. */
  const size_t stride = length % 16 == 0 ? 16 : (length % 8 == 0 ? 8 : 0);
  if (stride == 0) return 0;
  unsigned count = 0;
  for (size_t offset = 0; offset + stride <= length && count < capacity;
       offset += stride) {
    if (stride == 16) {
      out[count].address = (uint64_t(be32(bytes + offset)) << 32) |
                           be32(bytes + offset + 4);
      out[count].size = (uint64_t(be32(bytes + offset + 8)) << 32) |
                        be32(bytes + offset + 12);
    } else {
      out[count].address = be32(bytes + offset);
      out[count].size = be32(bytes + offset + 4);
    }
    if (out[count].size != 0 && out[count].address + out[count].size >= out[count].address)
      ++count;
  }
  return count;
}

static IORegistryEntry *nodeAt(const char *path)
{
  return path == nullptr ? nullptr : IORegistryEntry::fromPath(path, gIODTPlane);
}

static bool boardIsPolaris(void)
{
  IORegistryEntry *root = nodeAt("/");
  if (root == nullptr) return false;
  const bool match = compatibleContains(root, "xiaomi,polaris") &&
                     compatibleContains(root, "qcom,sdm845");
  root->release();
  return match;
}

static void publishRange(IOService *service, const char *prefix,
                         const Range *ranges, unsigned count)
{
  char key[64];
  snprintf(key, sizeof(key), "%s-resource-count", prefix);
  service->setProperty(key, count, 32);
  for (unsigned i = 0; i < count && i < 4; ++i) {
    snprintf(key, sizeof(key), "%s-resource-%u-address", prefix, i);
    service->setProperty(key, ranges[i].address, 64);
    snprintf(key, sizeof(key), "%s-resource-%u-size", prefix, i);
    service->setProperty(key, ranges[i].size, 64);
  }
}

} // namespace

class PolarisA630Probe : public IOService {
  OSDeclareDefaultStructors(PolarisA630Probe)
public:
  IOService *probe(IOService *provider, SInt32 *score) override
  {
    unsigned enabled = 0;
    if (provider == nullptr || !boardIsPolaris() ||
        !PE_parse_boot_argn("polaris-a630-probe", &enabled, sizeof(enabled)) ||
        enabled != 1) {
      return nullptr;
    }
    if (score != nullptr) *score += 25;
    return IOService::probe(provider, score);
  }

  bool start(IOService *provider) override
  {
    if (!IOService::start(provider) || !boardIsPolaris()) return false;

    IORegistryEntry *gpu = nodeAt("/soc/qcom,kgsl-3d0@5000000");
    IORegistryEntry *gmu = nodeAt("/soc/qcom,gmu");
    IORegistryEntry *smmu = nodeAt("/soc/arm,smmu-kgsl@5040000");
    Range ranges[4] = {};
    unsigned gpuCount = readRanges(gpu, ranges, 4);
    publishRange(this, "gpu", ranges, gpuCount);
    unsigned gmuCount = readRanges(gmu, ranges, 4);
    publishRange(this, "gmu", ranges, gmuCount);
    unsigned smmuCount = readRanges(smmu, ranges, 4);
    publishRange(this, "smmu", ranges, smmuCount);

    setProperty("polaris-a630-contract-version", 1U, 32);
    setProperty("polaris-a630-family", "Adreno 630 / A630v2");
    setProperty("polaris-a630-firmware-candidates",
                "a630_gmu.bin,a630_sqe.fw,a630_zap.mdt");
    /* The stock Polaris DT inventory contains both A630 revisions.  Do not
     * collapse that evidence into one chip ID before the selected DTB and a
     * safe runtime identification read have been captured. */
    setProperty("polaris-a630-chip-id-candidates", "0x06030000,0x06030001");
    setProperty("polaris-a630-chip-id-confirmed", false);
    setProperty("polaris-a630-gpu-mmio-performed", false);
    setProperty("polaris-a630-gpu-writes-performed", false);
    setProperty("polaris-a630-gmu-started", false);
    setProperty("polaris-a630-smmu-programmed", false);
    setProperty("polaris-a630-dma-created", false);
    setProperty("polaris-a630-darwin-driver-ready", false);
    setProperty("polaris-a630-state",
                (gpu != nullptr && gmu != nullptr && smmu != nullptr) ?
                "resource-only; GPU backend pending" :
                "resource-missing; GPU backend withheld");
    setName("PolarisA630Probe");
    registerService();
    IOLog("PolarisA630Probe: gpu=%u gmu=%u smmu=%u; MMIO=0 writes=0 DMA=0\\n",
          gpuCount, gmuCount, smmuCount);
    OSSafeReleaseNULL(gpu);
    OSSafeReleaseNULL(gmu);
    OSSafeReleaseNULL(smmu);
    return true;
  }
};

OSDefineMetaClassAndStructors(PolarisA630Probe, IOService)
