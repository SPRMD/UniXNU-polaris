// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "../drivers/GopFramebuffer/PolarisCpuScanout.h"
#include <cassert>
#include <cstring>
#include <cstdint>
#include <cstdio>

int main() {
    alignas(8) unsigned char destination[512], source[512], before[512];
    // Include odd widths, unaligned sources, different padding and row counts.
    for (unsigned width = 1; width <= 17; ++width) {
        for (unsigned height = 1; height <= 5; ++height) {
            for (unsigned skew = 0; skew < 4; ++skew) {
                PolarisScanoutLayout dst = {(width * 4 + 8) * height, width * 4 + 8, width, height, 1};
                PolarisScanoutLayout src = {(width * 4 + 3) * height, width * 4 + 3, width, height, 1};
                memset(destination, 0xcd, sizeof(destination));
                for (unsigned i = 0; i < sizeof(source); ++i) source[i] = (i * 31 + 17) & 255;
                assert(polaris_scanout_copy(destination, dst, source + skew, src));
                for (unsigned y = 0; y < height; ++y) {
                    assert(!memcmp(destination + y * dst.stride, source + skew + y * src.stride, width * 4));
                    for (unsigned x = width * 4; x < dst.stride; ++x) assert(destination[y * dst.stride + x] == 0xcd);
                }
                for (unsigned i = dst.bytes; i < sizeof(destination); ++i) assert(destination[i] == 0xcd);
            }
        }
    }
    PolarisScanoutLayout good = {32, 16, 3, 2, 1};
    memset(destination, 0xac, sizeof(destination));
    memcpy(before, destination, sizeof(before));
    auto reject = [&](PolarisScanoutLayout dst, PolarisScanoutLayout src) {
        assert(!polaris_scanout_copy(destination, dst, source, src));
        assert(!memcmp(before, destination, sizeof(before)));
    };
    for (unsigned field = 0; field < 9; ++field) {
        auto bad = good;
        switch (field) {
        case 0: bad.width = 0; break;
        case 1: bad.height = 0; break;
        case 2: bad.format = 0; break;
        case 3: bad.stride = 11; break;
        case 4: bad.bytes = 31; break;
        case 5: bad.stride = UINT64_MAX; break;
        case 6: bad.bytes = UINT64_MAX; break;
        case 7: bad.width = 16385; break;
        case 8: bad.height = 16385; break;
        }
        reject(bad, good);
        reject(good, bad);
    }
    auto mismatch = good; mismatch.width = 2; reject(good, mismatch);
    auto unaligned = good; unaligned.stride = 15; unaligned.bytes = 30; reject(unaligned, good);
    assert(!polaris_scanout_copy(destination + 1, good, source, good));
    assert(!polaris_scanout_copy(nullptr, good, source, good));
    assert(!polaris_scanout_copy(destination, good, nullptr, good));
    assert(!polaris_scanout_copy(destination, good, destination + 4, good));
    assert(!polaris_scanout_copy(destination + 4, good, destination, good));
    assert(!polaris_scanout_copy(destination, good, reinterpret_cast<void *>(UINTPTR_MAX - 15), good));
    assert(!memcmp(before, destination, sizeof(before)));
    puts("CPU scanout: 340 pixel/padding cases and invalid-input checks passed");
}
