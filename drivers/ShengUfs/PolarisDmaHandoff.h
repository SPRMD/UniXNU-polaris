// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
// Read-only validation, NOT an SMMU takeover. See README.md for provenance.
// Restrict this first backend to explicit SMMUv2 BYPASS entries and 32-bit DMA.
// Translated mappings (including Qualcomm's disabled-context bypass quirk),
// unmatched streams, extended IDs and disabled SMMUs require separate evidence.
template <class Read>
static const char *polarisDmaHandoff (uint64_t address, uint64_t bytes, Read read)
{
  if (!address || !bytes || address >= 0x100000000ULL || bytes > 0x100000000ULL - address)
    return "runtime requires DMA below 4 GiB";
  uint32_t control = read (0), id0 = read (0x20);
  if ((control & ((1U << 0) | (1U << 3))) || !(id0 & (1U << 27)))
    return "unsupported SMMU handoff mode";
  unsigned groups = id0 & 255;
  if (!groups || groups > 128) return "unsupported SMMU stream groups";
  // DT mask 0xf denotes all sixteen possible stream IDs, not just 0x100.
  for (unsigned sid = 0x100; sid <= 0x10f; ++sid) {
    unsigned matches = 0;
    for (unsigned i = 0; i < groups; ++i) {
      uint32_t smr = read (0x800 + 4 * i);
      if (!(smr & 0x80000000U)) continue;
      unsigned mask = (smr >> 16) & 0x7fff;
      if (((smr ^ sid) & 0x7fff & ~mask) != 0) continue;
      if (++matches != 1) return "overlapping UFS stream mappings";
      if (((read (0xc00 + 4 * i) >> 16) & 3) != 1)
        return "UFS stream is not explicit bypass";
    }
    if (matches != 1) return "UFS stream has no proven DMA mapping";
  }
  return nullptr;
}

static inline bool polarisCapacity (const uint8_t *data, uint64_t &bytes)
{
  uint32_t last = (uint32_t (data[0]) << 24) | (uint32_t (data[1]) << 16) |
                  (uint32_t (data[2]) << 8) | data[3];
  uint32_t size = (uint32_t (data[4]) << 24) | (uint32_t (data[5]) << 16) |
                  (uint32_t (data[6]) << 8) | data[7];
  // READ CAPACITY(10)'s sentinel requires READ CAPACITY(16), not truncation.
  if (size != 4096 || last == UINT32_MAX) return false;
  bytes = (uint64_t (last) + 1) * 4096;
  return true;
}
