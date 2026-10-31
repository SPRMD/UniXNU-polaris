// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <IOKit/IOReturn.h>
#include "../GopFramebuffer/PolarisCpuScanout.h"
class IOService;
class IOMemoryDescriptor;
struct PolarisDisplayRuntime;
struct PolarisDisplayTransfer { uint64_t sequence, bytes; };
extern "C" {
// Call once from a sleepable IOKit context after the board's GOP memory nub
// exists. verifiedFormat must come from the actual firmware handoff audit;
// PE_Video's depth alone does not identify channel order. No default format.
IOReturn polaris_display_create(IOService *gopNub, uint32_t verifiedFormat,
                                PolarisDisplayRuntime **out);
// Kernel-only: caller owns a stable, CPU-complete, linear source descriptor.
// The producer must exclude writes/GPU use until this synchronous call returns.
IOReturn polaris_display_present(PolarisDisplayRuntime *, IOMemoryDescriptor *,
                                 const PolarisScanoutLayout *, PolarisDisplayTransfer *);
void polaris_display_stop(PolarisDisplayRuntime *);
// Owner must drain ALL callers before destroy. Stop/present are serialized.
void polaris_display_destroy(PolarisDisplayRuntime *);
}
