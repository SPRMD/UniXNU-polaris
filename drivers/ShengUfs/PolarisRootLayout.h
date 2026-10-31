// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
// Derived from ShengUfs RootLayout.h; stricter Polaris darwin/raw-APFS policy.
// Ops: read(4K LBA, blocks, dst), begin/update/endDigest. Workspace must be heap
// allocated by the kernel caller. No publication or hardware policy in this file.
struct PolarisRootWindow {
  char name[32];
  uint64_t absolute, bytes;
  uint8_t sha256[32], containerUuid[16];
};
struct PolarisRootLayout {
  uint64_t first, last, imageBytes;
  PolarisRootWindow window[2];
};
struct PolarisRootWorkspace {
  uint8_t entries[16384];
  uint8_t scratch[131072];
};
static uint32_t pr32 (const uint8_t *p) {
  return uint32_t (p[0]) | uint32_t (p[1]) << 8 | uint32_t (p[2]) << 16 | uint32_t (p[3]) << 24;
}
static uint64_t pr64 (const uint8_t *p) { return pr32 (p) | uint64_t (pr32 (p + 4)) << 32; }
static bool prZero (const uint8_t *p, size_t n) {
  for (size_t i = 0; i < n; ++i) if (p[i]) return false;
  return true;
}
static uint32_t prCrc (const uint8_t *p, size_t n, bool header = false) {
  uint32_t crc = UINT32_MAX;
  for (size_t i = 0; i < n; ++i) {
    crc ^= header && i >= 16 && i < 20 ? 0 : p[i];
    for (unsigned bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1)));
  }
  return ~crc;
}
static bool prName (const uint8_t *p, const char *name, size_t bytes, unsigned stride = 1) {
  size_t n = strlen (name);
  if ((n + 1) * stride > bytes) return false;
  for (size_t i = 0; i < n; ++i)
    if (p[i * stride] != uint8_t (name[i]) || (stride == 2 && p[i * stride + 1])) return false;
  return prZero (p + n * stride, bytes - n * stride);
}
struct PolarisGpt {
  uint64_t first, last, entries;
  uint32_t count, crc;
  uint8_t guid[16];
};
static bool prHeader (const uint8_t *p, uint64_t blocks, bool backup, PolarisGpt &g) {
  // Supported subset: GPT 1.0, 92-byte header, <=128 128-byte entries.
  if (memcmp (p, "EFI PART", 8) || pr32 (p + 8) != 0x10000 || pr32 (p + 12) != 92 ||
      pr32 (p + 20) || !prZero (p + 92, 4096 - 92) ||
      prCrc (p, 92, true) != pr32 (p + 16) ||
      pr64 (p + 24) != (backup ? blocks - 1 : 1) ||
      pr64 (p + 32) != (backup ? 1 : blocks - 1) || pr32 (p + 84) != 128) return false;
  g.first = pr64 (p + 40); g.last = pr64 (p + 48); g.entries = pr64 (p + 72);
  g.count = pr32 (p + 80); g.crc = pr32 (p + 88); memcpy (g.guid, p + 56, 16);
  if (!g.count || g.count > 128 || prZero (g.guid, 16)) return false;
  uint64_t tableBlocks = (g.count * 128 + 4095) / 4096;
  if (g.first < 2 + tableBlocks || g.first > g.last || g.last >= blocks - 1 ||
      blocks - 1 - g.last <= tableBlocks || g.entries >= blocks ||
      tableBlocks > blocks - g.entries) return false;
  return backup ? (g.entries > g.last && g.entries + tableBlocks <= blocks - 1) :
                  (g.entries >= 2 && g.entries < g.first && tableBlocks <= g.first - g.entries);
}

template <class Ops>
static const char *polarisFindRoot (Ops &ops, uint64_t lunBytes, PolarisRootWorkspace &work,
                                   PolarisRootLayout &out) {
  out = {};
  PolarisRootLayout candidate = {};
  // Subtractions below are safe after this bounded READ(10) capacity check.
  if ((lunBytes & 4095) || lunBytes < 16 * 4096 || lunBytes / 4096 > uint64_t (UINT32_MAX) + 1)
    return "LUN capacity";
  uint64_t blocks = lunBytes / 4096;
  uint8_t *p = work.scratch;
  PolarisGpt primary, backup;
  if (!ops.read (1, 1, p) || !prHeader (p, blocks, false, primary)) return "primary GPT header/CRC";
  if (!ops.read (blocks - 1, 1, p) || !prHeader (p, blocks, true, backup)) return "backup GPT header/CRC";
  if (primary.first != backup.first || primary.last != backup.last || primary.count != backup.count ||
      primary.crc != backup.crc || memcmp (primary.guid, backup.guid, 16)) return "GPT headers disagree";
  uint32_t count = primary.count, tableBytes = count * 128, tableBlocks = (tableBytes + 4095) / 4096;
  if (!ops.read (primary.entries, tableBlocks, work.entries) ||
      prCrc (work.entries, tableBytes) != primary.crc) return "primary GPT array/CRC";
  if (!ops.read (backup.entries, tableBlocks, p) || prCrc (p, tableBytes) != backup.crc ||
      memcmp (p, work.entries, tableBytes)) return "backup GPT array/CRC";
  bool found = false;
  for (uint32_t i = 0; i < count; ++i) {
    const uint8_t *e = work.entries + i * 128;
    if (prZero (e, 16)) continue;
    uint64_t first = pr64 (e + 32), last = pr64 (e + 40);
    if (first < primary.first || last < first || last > primary.last || prZero (e + 16, 16))
      return "GPT partition bounds/GUID";
    for (uint32_t j = 0; j < i; ++j) {
      const uint8_t *other = work.entries + j * 128;
      if (prZero (other, 16)) continue;
      if (first <= pr64 (other + 40) && pr64 (other + 32) <= last) return "GPT partition overlap";
      if (!memcmp (e + 16, other + 16, 16) ||
          (!prZero (e + 56, 72) && !memcmp (e + 56, other + 56, 72))) return "duplicate GPT GUID/name";
    }
    if (prName (e + 56, "darwin", 72, 2)) {
      if (found) return "duplicate darwin";
      candidate.first = first; candidate.last = last; found = true;
    }
  }
  if (!found) return "no canonical darwin partition";
  uint64_t partitionBytes = (candidate.last - candidate.first + 1) * 4096;
  if (!ops.read (candidate.first, 1, p)) return "SHNGROOT read";
  if (memcmp (p, "SHNGROOT", 8) || pr32 (p + 8) != 1 || pr32 (p + 12) != 2)
    return "SHNGROOT version/count";
  uint8_t digest[32];
  ops.beginDigest (); ops.updateDigest (p, 4064); ops.endDigest (digest);
  if (memcmp (digest, p + 4064, 32)) return "SHNGROOT header SHA256";
  candidate.imageBytes = pr64 (p + 16);
  if (candidate.imageBytes < 4096 || (candidate.imageBytes & 4095) || candidate.imageBytes > partitionBytes ||
      !prZero (p + 24 + 256, 4064 - 24 - 256)) return "SHNGROOT image bounds/reserved";
  unsigned seen = 0;
  for (unsigned i = 0; i < 2; ++i) {
    const uint8_t *e = p + 24 + 128 * i;
    unsigned slot = prName (e, "SystemOS", 32) ? 0 : prName (e, "OS", 32) ? 1 : 2;
    if (slot == 2 || (seen & (1U << slot))) return "SHNGROOT duplicate/unknown window";
    seen |= 1U << slot;
    auto &w = candidate.window[slot];
    uint64_t offset = pr64 (e + 32), size = pr64 (e + 40);
    // Raw APFS occupies whole 4K blocks. Subtraction BEFORE addition/multiplication.
    if (offset < 4096 || (offset & 4095) || size < 4096 || (size & 4095) ||
        offset >= candidate.imageBytes || size > candidate.imageBytes - offset ||
        pr32 (e + 48) != 512 || pr32 (e + 52) != 1 || !prZero (e + 88, 40))
      return "SHNGROOT window bounds/attributes";
    memcpy (w.name, e, 32); memcpy (w.sha256, e + 56, 32);
    w.absolute = candidate.first * 4096 + offset; w.bytes = size;
    if (w.absolute >= lunBytes || size > lunBytes - w.absolute) return "window outside LUN";
  }
  const auto &a = candidate.window[0], &b = candidate.window[1];
  if (a.absolute < b.absolute + b.bytes && b.absolute < a.absolute + a.bytes) return "SHNGROOT overlap";
  for (unsigned i = 0; i < 2; ++i) {
    auto &w = candidate.window[i];
    if (!ops.read (w.absolute / 4096, 1, p)) return "APFS container read";
    // Apple APFS Reference nx_superblock_t: obj header 32 bytes, then magic,
    // block size, block count; container UUID at 72. No nested GPT decoding.
    if (memcmp (p + 32, "NXSB", 4) || pr32 (p + 36) != 4096 ||
        pr64 (p + 40) != w.bytes / 4096 || (pr32 (p + 24) & 0xffff) != 1 ||
        prZero (p + 72, 16)) return "window is not normalized raw 4K APFS";
    memcpy (w.containerUuid, p + 72, 16);
    ops.beginDigest ();
    for (uint64_t offset = 0; offset < w.bytes;) {
      uint64_t remaining = (w.bytes - offset) / 4096;
      uint32_t n = static_cast<uint32_t> (remaining > sizeof (work.scratch) / 4096 ?
                                        sizeof (work.scratch) / 4096 : remaining);
      if (!ops.read ((w.absolute + offset) / 4096, n, p)) return "window digest read";
      ops.updateDigest (p, n * 4096); offset += n * 4096;
    }
    ops.endDigest (digest);
    if (memcmp (digest, w.sha256, 32)) return "window SHA256 mismatch";
  }
  if (!memcmp (a.containerUuid, b.containerUuid, 16)) return "duplicate APFS container UUID";
  out = candidate; // Never expose a partially validated layout.
  return nullptr;
}
