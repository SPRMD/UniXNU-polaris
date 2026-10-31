// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
// Read-only validation, NOT an SMMU takeover. See README.md for provenance.
// Only explicit SMMUv2 BYPASS: runtime CAP + IDR2 widths bound the ENTIRE DMA
// allocation. ARM IHI 0062D.c 1.6.2/1.6.3/9.6.1; see DMA-HANDOFF.md.
// Translated mappings (including Qualcomm's disabled-context bypass quirk),
// unmatched streams, extended IDs and disabled SMMUs require separate evidence.
struct PolarisDmaEvidence {
  uint32_t cap = 0, control = 0, id0 = 0, id2 = 0;
  unsigned ias = 0, oas = 0, ubs = 0, limit = 0;
};
static inline unsigned polarisPhysicalAddressBits (unsigned code) {
  switch (code) {
    case 0: return 32; case 1: return 36; case 2: return 40;
    case 3: return 42; case 4: return 44; case 5: return 48;
    default: return 0; // Reserved, NOT Linux's default-to-48 fallback.
  }
}
static inline unsigned polarisUpstreamAddressBits (unsigned code) {
  if (code == 5) return 49;
  if (code == 15) return 64;
  return polarisPhysicalAddressBits (code);
}
static inline bool polarisDmaRangeFits (uint64_t address, uint64_t bytes, unsigned bits) {
  if (!address || !bytes || !bits || bits > 64) return false;
  uint64_t maximum = bits == 64 ? UINT64_MAX : (1ULL << bits) - 1;
  // Inclusive last-byte check avoids address+bytes wrap, including at 2^64.
  return address <= maximum && bytes - 1 <= maximum - address;
}
static inline bool polarisControllerDmaFits (uint64_t address, uint64_t bytes, uint32_t cap) {
  return polarisDmaRangeFits (address, bytes, (cap & (1U << 24)) ? 64 : 32);
}
template <class HostRead, class SmmuRead>
static const char *polarisDmaHandoff (uint64_t address, uint64_t bytes,
                                     HostRead hostRead, SmmuRead read, PolarisDmaEvidence &e)
{
  e = {};
  e.cap = hostRead (0x00);
  if (!polarisControllerDmaFits (address, bytes, e.cap)) return "DMA exceeds UFS CAP address width";
  e.control = read (0x00); e.id0 = read (0x20); e.id2 = read (0x28);
  if ((e.control & ((1U << 0) | (1U << 3))) || !(e.id0 & (1U << 27)))
    return "unsupported SMMU handoff mode";
  e.ias = polarisPhysicalAddressBits (e.id2 & 15);
  e.oas = polarisPhysicalAddressBits ((e.id2 >> 4) & 15);
  e.ubs = polarisUpstreamAddressBits ((e.id2 >> 8) & 15);
  if (!e.ias || !e.oas || !e.ubs) return "reserved SMMUv2 IDR2 address width";
  // Explicit BYPASS never reaches a translation context: IAS/PASize/VA64 do
  // not bound this route. UBS is the upstream port; OAS truncates its output.
  e.limit = e.ubs < e.oas ? e.ubs : e.oas;
  if (!(e.cap & (1U << 24)) && e.limit > 32) e.limit = 32;
  if (!polarisDmaRangeFits (address, bytes, e.limit)) return "DMA exceeds SMMU UBS/OAS width";
  unsigned groups = e.id0 & 255;
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
  // Do not accept a global handoff that changed while inspecting stream state.
  if (hostRead (0) != e.cap || read (0) != e.control || read (0x20) != e.id0 || read (0x28) != e.id2)
    return "DMA handoff registers changed";
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
