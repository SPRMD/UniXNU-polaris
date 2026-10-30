// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Bounded, transport-independent Synaptics RMI4/F12 decoding for Polaris.
// The functions in this header do not access a bus or allocate memory.  A
// future QUPv3/IOHID transport may use them only after the board resources and
// controller identity have been checked at runtime.

#ifndef POLARIS_SYNAPTICS_RMI4_PROTOCOL_H
#define POLARIS_SYNAPTICS_RMI4_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#define POLARIS_RMI4_PDT_ENTRY_BYTES 6u
#define POLARIS_RMI4_PDT_MAX_FUNCTIONS 10u
#define POLARIS_RMI4_F01_FUNCTION 0x01u
#define POLARIS_RMI4_F12_FUNCTION 0x12u
#define POLARIS_RMI4_F12_FRAME_BYTES 8u
#define POLARIS_RMI4_MAX_SLOTS 10u

typedef struct {
  uint8_t query_base;
  uint8_t command_base;
  uint8_t control_base;
  uint8_t data_base;
  uint8_t interrupt_source_count;
  uint8_t function_number;
} PolarisRmi4PdtEntry;

typedef struct {
  PolarisRmi4PdtEntry f01;
  PolarisRmi4PdtEntry f12;
  uint8_t has_f01;
  uint8_t has_f12;
  uint8_t terminated;
} PolarisRmi4Pdt;

typedef struct {
  uint8_t status;
  uint8_t present;
  uint16_t x;
  uint16_t y;
} PolarisRmi4Contact;

/* Decode a packed sequence of six-byte PDT entries.  The transport is
 * responsible for reading the entries from 0xE9 downward; this function only
 * validates the bounded snapshot and never changes a page register. */
static inline int polaris_rmi4_parse_pdt(const uint8_t *bytes, size_t length,
                                          PolarisRmi4Pdt *out)
{
  if (bytes == NULL || out == NULL || length == 0 ||
      length % POLARIS_RMI4_PDT_ENTRY_BYTES != 0) {
    return 0;
  }
  const size_t count = length / POLARIS_RMI4_PDT_ENTRY_BYTES;
  if (count > POLARIS_RMI4_PDT_MAX_FUNCTIONS) return 0;
  out->has_f01 = 0;
  out->has_f12 = 0;
  out->terminated = 0;
  for (size_t index = 0; index < count; ++index) {
    const uint8_t *p = bytes + index * POLARIS_RMI4_PDT_ENTRY_BYTES;
    PolarisRmi4PdtEntry entry = {p[0], p[1], p[2], p[3], p[4], p[5]};
    if (entry.function_number == 0) {
      out->terminated = 1;
      break;
    }
    if (entry.function_number == POLARIS_RMI4_F01_FUNCTION) {
      out->f01 = entry;
      out->has_f01 = 1;
    } else if (entry.function_number == POLARIS_RMI4_F12_FUNCTION) {
      out->f12 = entry;
      out->has_f12 = 1;
    }
  }
  return out->terminated && out->has_f01 && out->has_f12;
}

/* Decode one bounded RMI4/F12 object.  Status zero is release.  The
 * active object type is deliberately restricted to 1, matching the current
 * retired-chain evidence; unknown object types are rejected instead of being
 * exposed as input events. */
static inline int polaris_rmi4_parse_contact(const uint8_t *bytes, size_t length,
                                              uint16_t max_x, uint16_t max_y,
                                              PolarisRmi4Contact *out)
{
  if (bytes == NULL || out == NULL || length != POLARIS_RMI4_F12_FRAME_BYTES) {
    return 0;
  }
  const uint8_t status = bytes[0] & 0x0fu;
  const uint16_t x = (uint16_t)bytes[1] | (uint16_t)((uint16_t)bytes[2] << 8);
  const uint16_t y = (uint16_t)bytes[3] | (uint16_t)((uint16_t)bytes[4] << 8);
  out->status = status;
  out->x = x;
  out->y = y;
  out->present = 0;
  if (status == 0) return 1;
  /* The retired-chain evidence only established object type 1.  Refuse every other
   * non-zero type until a runtime capture proves its meaning. */
  if (status != 1) return 0;
  if (x >= max_x || y >= max_y) return 0;
  out->present = 1;
  return 1;
}

/* Decode a bounded set of fixed-size slots.  Releases remain in the output so
 * a future HID sink can retire contacts without inventing state. */
static inline int polaris_rmi4_parse_contacts(const uint8_t *bytes, size_t length,
                                               size_t slots, uint16_t max_x,
                                               uint16_t max_y,
                                               PolarisRmi4Contact *out,
                                               size_t out_slots)
{
  if (bytes == NULL || out == NULL || slots == 0 || slots > POLARIS_RMI4_MAX_SLOTS ||
      out_slots < slots || length != slots * POLARIS_RMI4_F12_FRAME_BYTES) {
    return 0;
  }
  for (size_t index = 0; index < slots; ++index) {
    if (!polaris_rmi4_parse_contact(bytes + index * POLARIS_RMI4_F12_FRAME_BYTES,
                                     POLARIS_RMI4_F12_FRAME_BYTES, max_x, max_y,
                                     &out[index])) {
      return 0;
    }
  }
  return 1;
}

#endif



