// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#include <stddef.h>

// Local IOSurface UUID f73d44bb-e674-36e7-a577-83789a86fe7a.
// Offsets are relative to that module's __TEXT_EXEC,__text, NOT the kernel.
// Audited local input SHA f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7.
struct PolarisSurfaceLeaf { uint32_t offset, instruction; };
enum { PDS_DESCRIPTOR, PDS_FORMAT, PDS_WIDTH, PDS_HEIGHT, PDS_STRIDE, PDS_PLANES, PDS_ALLOCATION, PDS_COUNT };
static constexpr PolarisSurfaceLeaf polaris_surface_leaves[PDS_COUNT] = {
    {0x8ad0, 0xf9401800}, // x0 = [x0+48], descriptor
    {0x8bac, 0xb9408000}, // w0 = [x0+128], pixel format
    {0x8bbc, 0xf9402c00}, // x0 = [x0+88], width
    {0x8bc4, 0xf9403000}, // x0 = [x0+96], height
    {0x8bd4, 0xf9403400}, // x0 = [x0+104], stride
    {0x8bf4, 0xb9409800}, // w0 = [x0+152], planes
    {0x8bfc, 0xf9404800}, // x0 = [x0+144], allocation
};
static inline bool polaris_surface_validate_code(const uint8_t uuid[16], const void *text, size_t bytes) {
    static constexpr uint8_t expected[16] = {0xf7,0x3d,0x44,0xbb,0xe6,0x74,0x36,0xe7,0xa5,0x77,0x83,0x78,0x9a,0x86,0xfe,0x7a};
    if (!uuid || !text || bytes != 0x22218 || (reinterpret_cast<uintptr_t>(text) & 3) ||
        bytes > UINTPTR_MAX - reinterpret_cast<uintptr_t>(text)) return false;
    for (unsigned i=0;i<16;++i) if(uuid[i]!=expected[i]) return false;
    auto code = static_cast<const unsigned char *>(text);
    for (const auto &leaf : polaris_surface_leaves) {
        uint32_t load, ret;
        __builtin_memcpy(&load, code + leaf.offset, 4);
        __builtin_memcpy(&ret, code + leaf.offset + 4, 4);
        if (load != leaf.instruction || ret != 0xd65f03c0) return false;
    }
    return true;
}
