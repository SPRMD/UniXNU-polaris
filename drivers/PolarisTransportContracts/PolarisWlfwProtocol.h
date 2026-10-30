// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// WCN399x WLFW board-data request helpers.  They build bounded QMI TLV
// payloads only; no QRTR/QMI transport, firmware loading, DMA or power vote is
// performed by this component.
#ifndef POLARIS_WLFW_PROTOCOL_H
#define POLARIS_WLFW_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

namespace PolarisWlfw {

enum { kBdfMessage = 0x25, kChunkSize = 6144, kOverhead = 34 };

static inline void put16(uint8_t *p, uint16_t value)
{
  p[0] = (uint8_t)value;
  p[1] = (uint8_t)(value >> 8);
}

static inline void put32(uint8_t *p, uint32_t value)
{
  put16(p, (uint16_t)value);
  put16(p + 2, (uint16_t)(value >> 16));
}

static inline uint16_t get16(const uint8_t *p)
{
  return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static inline size_t bdfRequest(const uint8_t *file, size_t total,
                                uint32_t segment, uint8_t *out,
                                size_t capacity)
{
  if (file == nullptr || out == nullptr || total == 0 || total > UINT32_MAX) {
    return 0;
  }
  const uint64_t offset = (uint64_t)segment * kChunkSize;
  if (offset >= total) return 0;
  const size_t left = total - (size_t)offset;
  const size_t count = left > kChunkSize ? kChunkSize : left;
  if (capacity < count + kOverhead) return 0;
  size_t index = 0;
  out[index++] = 1; put16(out + index, 1); index += 2; out[index++] = 1;
  out[index++] = 0x10; put16(out + index, 4); index += 2;
  put32(out + index, 0); index += 4;
  out[index++] = 0x11; put16(out + index, 4); index += 2;
  put32(out + index, (uint32_t)total); index += 4;
  out[index++] = 0x12; put16(out + index, 4); index += 2;
  put32(out + index, segment); index += 4;
  out[index++] = 0x13; put16(out + index, (uint16_t)(count + 2)); index += 2;
  put16(out + index, (uint16_t)count); index += 2;
  for (size_t j = 0; j < count; ++j) out[index++] = file[(size_t)offset + j];
  out[index++] = 0x14; put16(out + index, 1); index += 2;
  out[index++] = count == left ? 1 : 0;
  return index;
}

static inline bool bdfAccepted(const uint8_t *data, size_t size)
{
  return data != nullptr && size == 7 && data[0] == 2 &&
      get16(data + 1) == 4 && get16(data + 3) == 0 &&
      get16(data + 5) == 0;
}

} // namespace PolarisWlfw

#endif
