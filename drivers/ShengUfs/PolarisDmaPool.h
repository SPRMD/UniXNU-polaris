// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
// Read the optional low-address DMA pool that DarwinBoot reserved below 4 GiB.
//
// This removes the *address* axis only. A pool proves nothing about SMMU
// routing, controller quirks or the storage stack: polarisDmaHandoff() still
// runs against the pool address and can still refuse. When the loader
// published no pool, the caller keeps its previous behaviour (allocate from
// kernel_task and accept whatever address the guard permits).
//
// Encoding: the UniXNU ADT is the device-tree format DarwinBoot already parses
// with ReadUnaligned64, and DarwinBoot writes the slot with WriteUnaligned64,
// so the value is little-endian on this target. The parser below mirrors that;
// it never byte-swaps.
struct PolarisDmaPool {
  uint64_t base = 0;
  uint64_t bytes = 0;
  bool present = false;
};

// Bounds are duplicated from the loader on purpose: the kernel must not trust
// a bootloader-supplied range without checking it against its own contract.
static constexpr uint64_t kPolarisDmaPoolCeiling = 0x100000000ULL;
static constexpr uint64_t kPolarisDmaPoolMaxBytes = 4ULL * 1024ULL * 1024ULL;
static constexpr uint64_t kPolarisDmaPoolMinBytes = 64ULL * 1024ULL;

static inline bool polarisDmaPoolValid (const PolarisDmaPool &pool)
{
  if (!pool.base || !pool.bytes) return false;
  if (pool.bytes < kPolarisDmaPoolMinBytes || pool.bytes > kPolarisDmaPoolMaxBytes) return false;
  if ((pool.base & 0xfff) || (pool.bytes & 0xfff)) return false;
  if (pool.base > kPolarisDmaPoolCeiling) return false;
  return pool.bytes <= kPolarisDmaPoolCeiling - pool.base;
}

// Walk the ADT for /chosen/darwinboot-dma-pool. The pool is reported only when
// the loader actually reserved one; a zero slot (property present, nothing
// reserved) and an absent property are both "no pool", never an error.
static inline PolarisDmaPool polarisReadDmaPool (const uint8_t *data, unsigned size)
{
  PolarisDmaPool pool;
  if (!data || size < 8) return pool;
  const uint32_t properties = *reinterpret_cast<const uint32_t *> (data);
  const uint32_t children = *reinterpret_cast<const uint32_t *> (data + 4);
  unsigned offset = 8;
  const void *slot = nullptr;
  unsigned slotLength = 0;
  for (uint32_t index = 0; index < properties; ++index) {
    if (size - offset < 36) return pool;
    const char *name = reinterpret_cast<const char *> (data + offset);
    const uint32_t length = *reinterpret_cast<const uint32_t *> (data + offset + 32);
    offset += 36;
    if (length > size - offset) return pool;
    if (strncmp (name, "darwinboot-dma-pool", 32) == 0) {
      if (slot) return pool;  // duplicate property: refuse rather than guess
      slot = data + offset;
      slotLength = length;
    }
    offset = (offset + length + 3) & ~3u;
    if (offset > size) return pool;
  }
  (void) children;  // the pool lives directly under the root node's /chosen
  if (!slot || slotLength != 16) return pool;
  uint64_t base = 0, bytes = 0;
  for (unsigned i = 0; i < 8; ++i) {
    base |= static_cast<uint64_t> (static_cast<const uint8_t *> (slot)[i]) << (8 * i);
    bytes |= static_cast<uint64_t> (static_cast<const uint8_t *> (slot)[i + 8]) << (8 * i);
  }
  pool.base = base;
  pool.bytes = bytes;
  pool.present = polarisDmaPoolValid (pool);
  if (!pool.present) {
    pool.base = 0;
    pool.bytes = 0;
  }
  return pool;
}
