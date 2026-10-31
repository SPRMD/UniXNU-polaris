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
#include "PolarisA630Board.h"
#include "PolarisA630Policy.h"

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

static bool readBe32Property(IORegistryEntry *entry, const char *name,
                             uint32_t *value)
{
  if (entry == nullptr || name == nullptr || value == nullptr) return false;
  OSData *data = OSDynamicCast(OSData, entry->getProperty(name));
  if (data == nullptr || data->getBytesNoCopy() == nullptr ||
      data->getLength() < sizeof(uint32_t)) return false;
  const uint8_t *bytes = static_cast<const uint8_t *>(data->getBytesNoCopy());
  *value = be32(bytes + data->getLength() - sizeof(uint32_t));
  return true;
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

/* iommus tuples are {phandle, stream-id} pairs, not {address, size} ranges.
 * Reading them with readRanges() would silently reinterpret a SID as a size. */
static unsigned readStreamIds(IORegistryEntry *entry, uint32_t *out,
                              unsigned capacity)
{
  if (entry == nullptr || out == nullptr || capacity == 0) return 0;
  OSData *data = OSDynamicCast(OSData, entry->getProperty("iommus"));
  if (data == nullptr || data->getBytesNoCopy() == nullptr) return 0;
  const uint8_t *bytes = static_cast<const uint8_t *>(data->getBytesNoCopy());
  const size_t length = data->getLength();
  if (length == 0 || length % 8 != 0) return 0;
  unsigned count = 0;
  for (size_t offset = 0; offset + 8 <= length && count < capacity;
       offset += 8) {
    out[count++] = be32(bytes + offset + 4);  /* the SID, not the phandle */
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
    IORegistryEntry *gpucc = nodeAt("/soc/qcom,gpucc@5090000");
    IORegistryEntry *iommu = nodeAt("/soc/qcom,kgsl-iommu");
    Range gpuRanges[4] = {};
    Range gmuRanges[4] = {};
    Range smmuRanges[4] = {};
    Range gpuccRanges[4] = {};
    unsigned gpuCount = readRanges(gpu, gpuRanges, 4);
    publishRange(this, "gpu", gpuRanges, gpuCount);
    unsigned gmuCount = readRanges(gmu, gmuRanges, 4);
    publishRange(this, "gmu", gmuRanges, gmuCount);
    unsigned smmuCount = readRanges(smmu, smmuRanges, 4);
    publishRange(this, "smmu", smmuRanges, smmuCount);
    unsigned gpuccCount = readRanges(gpucc, gpuccRanges, 4);
    publishRange(this, "gpucc", gpuccRanges, gpuccCount);

    /* The second reg tuple of the GMU is the PDC window it shares; publish it
     * separately so a backend never has to re-derive it from a range list. */
    if (gmuCount >= 2) {
      setProperty("polaris-a630-gmu-pdc-base", gmuRanges[1].address, 64);
      setProperty("polaris-a630-gmu-pdc-bytes", gmuRanges[1].size, 64);
    }
    /* kgsl exposes three windows; the middle one is the CX debug block. */
    if (gpuCount >= 3) {
      setProperty("polaris-a630-gpu-cx-dbgc-base", gpuRanges[1].address, 64);
      setProperty("polaris-a630-gpu-cx-dbgc-bytes", gpuRanges[1].size, 64);
      setProperty("polaris-a630-gpu-cx-misc-base", gpuRanges[2].address, 64);
      setProperty("polaris-a630-gpu-cx-misc-bytes", gpuRanges[2].size, 64);
    }
    /* Context-bank stream IDs come from the iommus tuples, never guessed.
     * gfx3d_user -> {phandle, 0}; gfx3d_secure -> {phandle, 2} and {phandle, 1}. */
    uint32_t sids[8] = {};
    unsigned sidCount = 0;
    if (iommu != nullptr) {
      IORegistryEntry *user = nodeAt("/soc/qcom,kgsl-iommu/gfx3d_user");
      IORegistryEntry *secure = nodeAt("/soc/qcom,kgsl-iommu/gfx3d_secure");
      uint32_t userSids[2] = {};
      uint32_t secureSids[2] = {};
      const unsigned userCount = readStreamIds(user, userSids, 2);
      const unsigned secureCount = readStreamIds(secure, secureSids, 2);
      for (unsigned i = 0; i < userCount && sidCount < 8; ++i)
        sids[sidCount++] = userSids[i];
      for (unsigned i = 0; i < secureCount && sidCount < 8; ++i)
        sids[sidCount++] = secureSids[i];
      setProperty("polaris-a630-gfx3d-user-sid-count", userCount, 32);
      setProperty("polaris-a630-gfx3d-secure-sid-count", secureCount, 32);
      OSSafeReleaseNULL(user);
      OSSafeReleaseNULL(secure);
    }
    setProperty("polaris-a630-gpu-iommu-node-present", iommu != nullptr);
    setProperty("polaris-a630-gpu-sid-count", sidCount, 32);
    for (unsigned i = 0; i < sidCount; ++i) {
      char key[64];
      snprintf(key, sizeof(key), "polaris-a630-gpu-sid-%u", i);
      setProperty(key, sids[i], 32);
    }
    /* The DT-declared set must be exactly the three SIDs this contract names;
     * a mismatch means the tree changed and the backend must not assume them. */
    bool sidsMatch = (sidCount == POLARIS_A630_GPU_SID_COUNT);
    if (sidsMatch) {
      bool sawGpu = false, sawSecureA = false, sawSecureB = false;
      for (unsigned i = 0; i < sidCount; ++i) {
        sawGpu |= sids[i] == POLARIS_A630_GPU_SID;
        sawSecureA |= sids[i] == POLARIS_A630_GPU_SECURE_SID_A;
        sawSecureB |= sids[i] == POLARIS_A630_GPU_SECURE_SID_B;
      }
      sidsMatch = sawGpu && sawSecureA && sawSecureB;
    }
    setProperty("polaris-a630-gpu-sids-match-contract", sidsMatch);

    uint32_t dtChipId = 0;
    uint32_t dtHighestBankBit = 0;
    const bool dtChipIdPresent = readBe32Property(gpu, "qcom,chipid", &dtChipId);
    const bool dtHighestBankBitPresent =
        readBe32Property(gpu, "qcom,highest-bank-bit", &dtHighestBankBit);
    setProperty("polaris-a630-dt-chip-id-present", dtChipIdPresent);
    if (dtChipIdPresent) setProperty("polaris-a630-dt-chip-id", dtChipId, 32);
    setProperty("polaris-a630-dt-highest-bank-bit-present",
                dtHighestBankBitPresent);
    if (dtHighestBankBitPresent)
      setProperty("polaris-a630-dt-highest-bank-bit", dtHighestBankBit, 32);
    setProperty("polaris-a630-gpu-irq-spi-candidate",
                POLARIS_A630_GPU_IRQ_SPI, 32);
    setProperty("polaris-a630-gmu-hfi-irq-spi-candidate",
                POLARIS_A630_GMU_HFI_IRQ_SPI, 32);
    setProperty("polaris-a630-gmu-irq-spi-candidate",
                POLARIS_A630_GMU_IRQ_SPI, 32);
    setProperty("polaris-a630-smmu-global-irq0-spi-candidate",
                POLARIS_A630_SMMU_GLOBAL_IRQ0_SPI, 32);
    setProperty("polaris-a630-smmu-global-irq1-spi-candidate",
                POLARIS_A630_SMMU_GLOBAL_IRQ1_SPI, 32);

    PolarisA630Evidence evidence = {};
    evidence.board_matches = 1;
    evidence.gpu_present = (gpu != nullptr && gpuCount != 0);
    evidence.gmu_present = (gmu != nullptr && gmuCount != 0);
    evidence.smmu_present = (smmu != nullptr && smmuCount != 0);
    if (gpuCount != 0) {
      evidence.gpu.address = gpuRanges[0].address;
      evidence.gpu.size = gpuRanges[0].size;
    }
    if (gmuCount != 0) {
      evidence.gmu.address = gmuRanges[0].address;
      evidence.gmu.size = gmuRanges[0].size;
    }
    if (smmuCount != 0) {
      evidence.smmu.address = smmuRanges[0].address;
      evidence.smmu.size = smmuRanges[0].size;
    }
    /* The probe never reads a live chip ID or loads private firmware. */
    /* A DT qcom,chipid is static evidence, not a live GPU identity read. */
    evidence.chip_id = dtChipId;
    evidence.chip_id_confirmed = 0;
    evidence.firmware_complete = 0;
    PolarisA630Plan plan = polaris_a630_make_plan(evidence);
    setProperty("polaris-a630-resource-contract-valid",
                plan.resource_contract_valid, 32);
    setProperty("polaris-a630-hardware-writes-allowed",
                plan.hardware_writes_allowed, 32);
    setProperty("polaris-a630-firmware-load-allowed",
                plan.firmware_load_allowed, 32);
    setProperty("polaris-a630-dma-allowed", plan.dma_allowed, 32);
    setProperty("polaris-a630-plan-reason", plan.reason, 32);

    setProperty("polaris-a630-contract-version", 1U, 32);
    setProperty("polaris-a630-family", "Adreno 630 / A630v2");
    setProperty("polaris-a630-firmware-candidates",
                "a630_gmu.bin,a630_sqe.fw,a630_zap.mdt");
    /* The stock Polaris DT declares one revision, 0x06030001. That is a
     * firmware claim about the part, still not a live read from this GPU: the
     * probe never maps the GPU, so chip_id_confirmed above stays 0. */
    setProperty("polaris-a630-chip-id-dt-declared", POLARIS_A630_CHIP_ID_DT_DECLARED, 32);
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
    setProperty("polaris-a630-resource-source",
                "stock Polaris DT (qcom,sdm845-mtp); no live MMIO");
    setName("PolarisA630Probe");
    registerService();
    IOLog("PolarisA630Probe: gpu=%u gmu=%u smmu=%u; MMIO=0 writes=0 DMA=0\\n",
          gpuCount, gmuCount, smmuCount);
    OSSafeReleaseNULL(gpu);
    OSSafeReleaseNULL(gmu);
    OSSafeReleaseNULL(smmu);
    OSSafeReleaseNULL(gpucc);
    OSSafeReleaseNULL(iommu);
    return true;
  }
};

OSDefineMetaClassAndStructors(PolarisA630Probe, IOService)
