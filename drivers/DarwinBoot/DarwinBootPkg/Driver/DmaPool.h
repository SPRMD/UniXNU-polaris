// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef DARWINBOOT_DMA_POOL_H
#define DARWINBOOT_DMA_POOL_H

// An OPTIONAL low-address DMA pool for a device whose bus master cannot be
// proven to address the upper DDR bank. This header decides only *whether the
// firmware may hand out a pool at all*; the actual pages still come from
// AllocatePages against the real UEFI memory map, exactly like the kernel
// window. Nothing here claims the pool makes a device work.
//
// Why a pool exists: polaris supplies the kernel window from the upper bank
// (>= 4 GiB), so every kernel IOBufferMemoryDescriptor lands above 4 GiB. A
// controller limited to 32-bit addresses cannot use those buffers, and the
// tree must not assume the apps-SMMU routes them. A pool the loader really
// owns, below 4 GiB, removes the *address* axis only.

// Largest pool the loader will ever reserve. Small on purpose: one UFS command
// needs a request descriptor + PRDT + a data buffer, not megabytes.
#define DARWIN_DMA_POOL_MAX_BYTES  (4ULL * 1024ULL * 1024ULL)
// Never reserve less than this; a smaller pool cannot hold a useful transfer.
#define DARWIN_DMA_POOL_MIN_BYTES  (64ULL * 1024ULL)

// Everything below 4 GiB is addressable by a 32-bit bus master.
#define DARWIN_DMA_POOL_CEILING    0x100000000ULL

typedef struct {
  UINT64 Base;
  UINT64 Bytes;
} DARWIN_DMA_POOL;

// The pool must be page aligned, non-empty, inside the 32-bit window, and small
// enough to be a pool rather than a second kernel window.
static inline int DarwinDmaPoolValid(UINT64 Base, UINT64 Bytes)
{
  if ((Base == 0) || (Bytes < DARWIN_DMA_POOL_MIN_BYTES) || (Bytes > DARWIN_DMA_POOL_MAX_BYTES)) { return 0; }
  if ((Base & 0xfffULL) || (Bytes & 0xfffULL)) { return 0; }
  if (Base > DARWIN_DMA_POOL_CEILING) { return 0; }
  if (Bytes > DARWIN_DMA_POOL_CEILING - Base) { return 0; }
  return 1;
}

// A conventional-memory run is a candidate only when the whole pool fits in it
// and stays strictly below 4 GiB. RunEnd is exclusive.
static inline int DarwinDmaPoolCandidate(UINT64 RunStart, UINT64 RunEnd,
    UINT64 Bytes, UINT64 *Base)
{
  UINT64 start;
  if (!Base || (RunEnd <= RunStart) || (Bytes < DARWIN_DMA_POOL_MIN_BYTES) ||
      (Bytes > DARWIN_DMA_POOL_MAX_BYTES) || (Bytes & 0xfffULL)) { return 0; }
  if (RunStart >= DARWIN_DMA_POOL_CEILING) { return 0; }
  if (RunEnd > DARWIN_DMA_POOL_CEILING) { RunEnd = DARWIN_DMA_POOL_CEILING; }
  // Page-align upwards; the caller re-checks with DarwinDmaPoolValid.
  if (RunStart > ~0ULL - 0xfffULL) { return 0; }
  start = (RunStart + 0xfffULL) & ~0xfffULL;
  if (start >= RunEnd || Bytes > RunEnd - start) { return 0; }
  *Base = start;
  return 1;
}

// Overlap test against every range the driver and the SoC carve-outs own. The
// pool must not collide with the UFS host controller, the apps-SMMU, the
// kernel window, the ADT, or any range the firmware marked reserved.
static inline int DarwinDmaPoolOverlaps(UINT64 Base, UINT64 Bytes,
    UINT64 OtherBase, UINT64 OtherBytes)
{
  if (!Bytes || !OtherBytes) { return 0; }
  return (Base < OtherBase + OtherBytes) && (OtherBase < Base + Bytes);
}

#endif
