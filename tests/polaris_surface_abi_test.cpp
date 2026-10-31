// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "../drivers/PolarisDisplayRuntime/PolarisSurfaceABI.h"
#include <cassert>
#include <cstring>
#include <cstdio>
int main() {
    alignas(8) unsigned char code[0x22218] = {};
    uint8_t uuid[16] = {0xf7,0x3d,0x44,0xbb,0xe6,0x74,0x36,0xe7,0xa5,0x77,0x83,0x78,0x9a,0x86,0xfe,0x7a};
    for (auto leaf : polaris_surface_leaves) {
        const uint32_t ret = 0xd65f03c0;
        memcpy(code + leaf.offset, &leaf.instruction, 4);
        memcpy(code + leaf.offset + 4, &ret, 4);
    }
    assert(polaris_surface_validate_code(uuid, code, sizeof(code)));
    assert(!polaris_surface_validate_code(uuid, code, sizeof(code)-1));
    assert(!polaris_surface_validate_code(nullptr, code, sizeof(code)));
    assert(!polaris_surface_validate_code(uuid, nullptr, sizeof(code)));
    for (unsigned i=0;i<16;++i) {
        uuid[i]^=1; assert(!polaris_surface_validate_code(uuid, code, sizeof(code))); uuid[i]^=1;
    }
    for (auto leaf : polaris_surface_leaves) for (unsigned i=0;i<8;++i) {
        code[leaf.offset+i]^=1;
        assert(!polaris_surface_validate_code(uuid, code, sizeof(code)));
        code[leaf.offset+i]^=1;
    }
    puts("Surface ABI: valid binding and all UUID/getter-byte mutations checked");
}
