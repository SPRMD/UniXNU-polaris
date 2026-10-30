// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Transport-independent WCN399x HCI framing helpers for Polaris.
// Adapted from the local Polaris driver research tree.  These helpers do not
// open a UART, load firmware, touch GPIOs, or access the wireless chip.
#ifndef POLARIS_QCA_PROTOCOL_H
#define POLARIS_QCA_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

namespace PolarisQca {

enum { kMaxSegment = 243, kMaxEvent = 258 };

struct Version {
  uint32_t product;
  uint16_t patch;
  uint16_t rom;
  uint32_t soc;
};

static inline size_t versionRequest(uint8_t *out, size_t cap)
{
  if (out == nullptr || cap < 5) return 0;
  out[0] = 1; out[1] = 0; out[2] = 0xfc; out[3] = 1; out[4] = 0x19;
  return 5;
}

static inline size_t segmentRequest(const uint8_t *data, size_t len,
                                    uint8_t *out, size_t cap)
{
  if (data == nullptr || out == nullptr || len == 0 || len > kMaxSegment ||
      cap < len + 6) return 0;
  out[0] = 1; out[1] = 0; out[2] = 0xfc; out[3] = (uint8_t)(len + 2);
  out[4] = 0x1e; out[5] = (uint8_t)len;
  for (size_t i = 0; i < len; ++i) out[6 + i] = data[i];
  return len + 6;
}

static inline uint16_t le16(const uint8_t *p)
{
  return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static inline uint32_t le32(const uint8_t *p)
{
  return (uint32_t)le16(p) | ((uint32_t)le16(p + 2) << 16);
}

static inline bool parseVersionEvent(const uint8_t *event, size_t len,
                                     Version *out)
{
  if (event == nullptr || out == nullptr || len != 17 || event[0] != 4 ||
      event[1] != 0xff || event[2] != 14 || event[3] != 0 ||
      event[4] != 2) return false;
  Version v = {le32(event + 5), le16(event + 9), le16(event + 11),
               le32(event + 13)};
  if (v.rom == 0 || v.soc == 0) return false;
  *out = v;
  return true;
}

static inline bool parseSegmentEvent(const uint8_t *event, size_t len)
{
  return event != nullptr && len == 6 && event[0] == 4 && event[1] == 0xff &&
      event[2] == 3 && event[3] == 0 && event[4] == 4 && event[5] == 0;
}

struct EventReader {
  uint8_t bytes[kMaxEvent];
  size_t used;
  size_t expected;

  void reset() { used = 0; expected = 0; }

  int feed(uint8_t byte)
  {
    if (expected != 0 && used == expected) return -1;
    if (used == 0 && byte != 4) return -1;
    if (used >= kMaxEvent) { reset(); return -1; }
    bytes[used++] = byte;
    if (used == 3) expected = (size_t)bytes[2] + 3;
    return expected != 0 && used == expected ? 1 : 0;
  }
};

} // namespace PolarisQca

#endif
