// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <IOKit/IOReturn.h>
#include "../GopFramebuffer/PolarisCpuScanout.h"
class IOService;
class IOMemoryDescriptor;
class OSObject;
struct PolarisDisplayRuntime;
struct PolarisSurfaceAdapter;
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
// Trusted prelink loader only: pass the admitted IOSurface module's LC_UUID
// and live executable __TEXT_EXEC,__text span, after relocations. The module
// must stay loaded and immutable until adapter destruction. Never user input.
IOReturn polaris_surface_adapter_create(const uint8_t uuid[16], const void *liveText,
                                        size_t textBytes, PolarisSurfaceAdapter **);
// Producer must hold a real IOSurface, keep its backing/geometry stable and
// wait for CPU rendering / fences before this call. No queue retirement here.
IOReturn polaris_surface_present(PolarisSurfaceAdapter *, PolarisDisplayRuntime *,
                                 OSObject *surface, PolarisDisplayTransfer *);
// Drain callers first; does not destroy the display runtime or unload IOSurface.
void polaris_surface_adapter_destroy(PolarisSurfaceAdapter *);
}
