// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

// Little-endian B,G,R,X bytes. No scaling, rotation, alpha blending or tiling.
enum { POLARIS_SCANOUT_BGRX8888 = 1, POLARIS_SCANOUT_MAX_BYTES = 64 * 1024 * 1024 };
struct PolarisScanoutLayout {
    uint64_t bytes, stride;
    uint32_t width, height, format;
};
// Validates the whole padded allocation before touching any memory.
bool polaris_scanout_layout_valid(const PolarisScanoutLayout &layout);
// Source may be unaligned. Destination must support aligned 32-bit stores.
// Returns false without writes on invalid geometry or overlapping VA ranges.
bool polaris_scanout_copy(volatile void *destination, const PolarisScanoutLayout &dst,
                          const void *source, const PolarisScanoutLayout &src);
