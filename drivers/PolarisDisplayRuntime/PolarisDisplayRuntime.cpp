// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "PolarisDisplayRuntime.h"
#include <IOKit/IOService.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <libkern/c++/OSData.h>
#include <pexpert/pexpert.h>

struct PolarisDisplayRuntime {
    IOLock *lock;
    IOMemoryMap *mapping;
    PolarisScanoutLayout mode;
    uint64_t physical, sequence;
};

static bool boardIsPolaris() {
    IORegistryEntry *root = IORegistryEntry::fromPath("/", gIODTPlane);
    if (!root) return false;
    OSData *data = OSDynamicCast(OSData, root->getProperty("compatible"));
    bool polaris = false, sdm845 = false;
    if (data && data->getBytesNoCopy()) {
        auto p = static_cast<const char *>(data->getBytesNoCopy());
        size_t n = data->getLength(), pos = 0;
        while (pos < n) {
            size_t end = pos;
            while (end < n && p[end]) ++end;
            if (end == n) { polaris = sdm845 = false; break; }
            polaris |= end - pos == sizeof("xiaomi,polaris") - 1 &&
                       !memcmp(p + pos, "xiaomi,polaris", sizeof("xiaomi,polaris") - 1);
            sdm845 |= end - pos == sizeof("qcom,sdm845") - 1 &&
                      !memcmp(p + pos, "qcom,sdm845", sizeof("qcom,sdm845") - 1);
            pos = end + 1;
        }
    }
    root->release();
    return polaris && sdm845;
}

IOReturn polaris_display_create(IOService *nub, uint32_t format, PolarisDisplayRuntime **out) {
    if (!out) return kIOReturnBadArgument;
    *out = nullptr;
    unsigned enabled = 0;
    PE_parse_boot_argn("polaris-cpu-display", &enabled, sizeof(enabled));
    if (enabled != 1 || !boardIsPolaris()) return kIOReturnUnsupported;
    if (!nub || format != POLARIS_SCANOUT_BGRX8888) return kIOReturnBadArgument;
    PE_Video v = {};
    if (PE_current_console(&v) || !v.v_baseAddr || v.v_depth != 32 || v.v_rotate ||
        !v.v_height || v.v_height > 16384 || !v.v_width || v.v_width > 16384 ||
        v.v_rowBytes > POLARIS_SCANOUT_MAX_BYTES / v.v_height) return kIOReturnUnsupported;
    PolarisScanoutLayout mode = {uint64_t(v.v_rowBytes) * v.v_height, v.v_rowBytes,
                                 uint32_t(v.v_width), uint32_t(v.v_height), format};
    if (!polaris_scanout_layout_valid(mode) || (mode.stride & 3) || (v.v_baseAddr & 3) ||
        v.v_baseAddr > UINT64_MAX - mode.bytes) return kIOReturnBadArgument;
    // Require the board nub's exact inherited GOP range, never a guessed MMIO address.
    IOMemoryDescriptor *range = nub->getDeviceMemoryWithIndex(0);
    IOByteCount contiguous = 0;
    if (!range || range->getLength() != mode.bytes ||
        range->getPhysicalSegment(0, &contiguous, kIOMemoryMapperNone) != v.v_baseAddr ||
        contiguous < mode.bytes) return kIOReturnBadArgument;
    auto ctx = static_cast<PolarisDisplayRuntime *>(IOMalloc(sizeof(PolarisDisplayRuntime)));
    if (!ctx) return kIOReturnNoMemory;
    bzero(ctx, sizeof(*ctx));
    ctx->lock = IOLockAlloc();
    ctx->mapping = nub->mapDeviceMemoryWithIndex(0, kIOMapInhibitCache);
    ctx->mode = mode;
    ctx->physical = v.v_baseAddr;
    if (!ctx->lock || !ctx->mapping || !ctx->mapping->getVirtualAddress() ||
        ctx->mapping->getPhysicalAddress() != ctx->physical || ctx->mapping->getLength() != mode.bytes) {
        if (ctx->mapping) ctx->mapping->release();
        if (ctx->lock) IOLockFree(ctx->lock);
        IOFree(ctx, sizeof(*ctx));
        return kIOReturnNoMemory;
    }
    *out = ctx;
    return kIOReturnSuccess;
}

// Reject even different virtual mappings of the scanout: the copy core can
// check VA overlap only. Source must have identifiable non-overlapping pages.
static bool sourceDisjoint(IOMemoryDescriptor *source, uint64_t base, uint64_t bytes) {
    uint64_t offset = 0, length = source->getLength();
    while (offset < length) {
        IOByteCount count = 0;
        uint64_t pa = source->getPhysicalSegment(offset, &count, kIOMemoryMapperNone);
        if (!pa || !count || count > length - offset || pa > UINT64_MAX - count ||
            (pa < base + bytes && base < pa + count)) return false;
        offset += count;
    }
    return true;
}

IOReturn polaris_display_present(PolarisDisplayRuntime *ctx, IOMemoryDescriptor *source,
                                 const PolarisScanoutLayout *layout, PolarisDisplayTransfer *out) {
    if (out) *out = {};
    if (!ctx || !source || !layout || !out) return kIOReturnBadArgument;
    const PolarisScanoutLayout frame = *layout;
    if (!polaris_scanout_layout_valid(frame) || frame.width != ctx->mode.width ||
        frame.height != ctx->mode.height || source->getLength() != frame.bytes) return kIOReturnBadArgument;
    IOLockLock(ctx->lock);
    if (!ctx->mapping) { IOLockUnlock(ctx->lock); return kIOReturnNotReady; }
    IOReturn status = source->prepare(kIODirectionIn);
    if (status == kIOReturnSuccess) {
        IOMemoryMap *input = nullptr;
        if (!sourceDisjoint(source, ctx->physical, ctx->mode.bytes)) status = kIOReturnBadArgument;
        else input = source->map(kIOMapAnywhere | kIOMapReadOnly);
        if (status == kIOReturnSuccess) {
            if (!input || !input->getVirtualAddress() || input->getLength() < frame.bytes) status = kIOReturnNoMemory;
            else if (!polaris_scanout_copy(reinterpret_cast<volatile void *>(ctx->mapping->getVirtualAddress()),
                                           ctx->mode, reinterpret_cast<const void *>(input->getVirtualAddress()), frame))
                status = kIOReturnBadArgument;
        }
        if (input) input->release();
        IOReturn completed = source->complete(kIODirectionIn);
        if (status == kIOReturnSuccess) status = completed;
        if (status == kIOReturnSuccess) {
            out->sequence = ++ctx->sequence;
            out->bytes = uint64_t(frame.width) * frame.height * 4;
        }
    }
    IOLockUnlock(ctx->lock);
    return status;
}

void polaris_display_stop(PolarisDisplayRuntime *ctx) {
    if (!ctx) return;
    IOLockLock(ctx->lock);
    if (ctx->mapping) { ctx->mapping->release(); ctx->mapping = nullptr; }
    IOLockUnlock(ctx->lock);
}
void polaris_display_destroy(PolarisDisplayRuntime *ctx) {
    if (!ctx) return;
    polaris_display_stop(ctx);
    IOLockFree(ctx->lock);
    IOFree(ctx, sizeof(*ctx));
}
