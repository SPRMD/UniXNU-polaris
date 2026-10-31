// SPDX-License-Identifier: BSD-2-Clause-Patent
// CPU transfer pattern reviewed against UniXNU NativeLegacyRequest.h; kept
// separate from all private Apple framebuffer class and swap-request layouts.
#include "PolarisCpuScanout.h"

bool polaris_scanout_layout_valid(const PolarisScanoutLayout &l) {
    return l.format == POLARIS_SCANOUT_BGRX8888 && l.width && l.height &&
           l.width <= 16384 && l.height <= 16384 && l.stride >= uint64_t(l.width) * 4 &&
           l.bytes <= POLARIS_SCANOUT_MAX_BYTES && l.stride <= l.bytes / l.height;
}

bool polaris_scanout_copy(volatile void *destination, const PolarisScanoutLayout &dst,
                          const void *source, const PolarisScanoutLayout &src) {
    const uintptr_t d = reinterpret_cast<uintptr_t>(destination);
    const uintptr_t s = reinterpret_cast<uintptr_t>(source);
    if (!polaris_scanout_layout_valid(dst) || !polaris_scanout_layout_valid(src) ||
        dst.width != src.width || dst.height != src.height || !d || !s ||
        (d & 3) || (dst.stride & 3) || dst.bytes > UINTPTR_MAX - d ||
        src.bytes > UINTPTR_MAX - s || (d < s + src.bytes && s < d + dst.bytes)) return false;
    for (uint32_t y = 0; y < dst.height; ++y) {
        auto out = reinterpret_cast<volatile uint32_t *>(d + y * dst.stride);
        auto in = reinterpret_cast<const unsigned char *>(s + y * src.stride);
        for (uint32_t x = 0; x < dst.width; ++x) {
            uint32_t pixel;
            __builtin_memcpy(&pixel, in + uint64_t(x) * 4, sizeof(pixel));
            out[x] = pixel;
        }
    }
    // This orders device stores; it is NOT a vblank or proof of panel refresh.
#if defined(__aarch64__) || defined(__arm64__)
    __asm__ volatile("dsb sy" ::: "memory");
#else
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
#endif
    return true;
}
