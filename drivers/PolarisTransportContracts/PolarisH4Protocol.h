// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Bounded Qualcomm H4 framing helpers for the Polaris WCN3998 candidate.
// These routines only encode/decode byte streams.  They do not open a UART,
// claim an interrupt, change baud rate, vote power, or load firmware.
#ifndef POLARIS_H4_PROTOCOL_H
#define POLARIS_H4_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#include "PolarisQcaProtocol.h"

namespace PolarisH4 {

enum : uint8_t {
  kCommand = 0x01,
  kAcl = 0x02,
  kEvent = 0x04,
};

enum : size_t {
  kHeaderSize = 3,
  kMaxPayload = 255,
  kMaxPacket = kHeaderSize + kMaxPayload,
};

static inline size_t command(uint16_t opcode, const uint8_t *params,
                             size_t length, uint8_t *out, size_t capacity)
{
  if (out == nullptr || length > kMaxPayload || capacity < length + 4 ||
      (length != 0 && params == nullptr)) return 0;
  out[0] = kCommand;
  out[1] = (uint8_t)opcode;
  out[2] = (uint8_t)(opcode >> 8);
  out[3] = (uint8_t)length;
  for (size_t i = 0; i < length; ++i) out[4 + i] = params[i];
  return length + 4;
}

struct Reader {
  uint8_t bytes[kMaxPacket + 1];
  size_t used;
  size_t expected;
  uint8_t packetType;

  void reset()
  {
    used = 0;
    expected = 0;
    packetType = 0;
  }

  int feed(uint8_t byte)
  {
    if (used == 0) {
      if (byte != kEvent && byte != kCommand && byte != kAcl) return -1;
      packetType = byte;
      bytes[used++] = byte;
      return 0;
    }
    if (expected != 0 && used == expected) return -1;
    if (used >= sizeof(bytes)) {
      reset();
      return -1;
    }
    bytes[used++] = byte;
    if (packetType == kEvent && used == 3) {
      expected = (size_t)bytes[2] + 3;
    } else if (packetType == kCommand && used == 4) {
      expected = (size_t)bytes[3] + 4;
    } else if (packetType == kAcl && used == 5) {
      expected = (size_t)bytes[3] | ((size_t)bytes[4] << 8);
      expected += 5;
    }
    if (expected > sizeof(bytes)) {
      reset();
      return -1;
    }
    return expected != 0 && used == expected ? 1 : 0;
  }

  bool complete() const { return expected != 0 && used == expected; }
};

static inline bool isEvent(const Reader &reader)
{
  return reader.complete() && reader.packetType == kEvent;
}

/*
 * Side-effect-free QCA firmware protocol session.  The session owns no
 * transport and never reads a file or touches hardware; callers provide one
 * bounded segment at a time and feed the corresponding H4 event back in.
 * Keeping this state machine here prevents a future UART backend from
 * advancing the segment counter before the controller acknowledges it.
 */
class QcaFirmwareSession {
public:
  enum State { Idle, AwaitVersion, ReadyForSegment, AwaitSegment, Complete, Failed };
  enum : size_t { kMaxFileBytes = 16u * 1024u * 1024u };

  QcaFirmwareSession()
      : state_(Idle), total_(0), segment_(0), segments_(0), version_{} {}

  void reset()
  {
    state_ = Idle;
    total_ = 0;
    segment_ = 0;
    segments_ = 0;
    version_ = {};
  }

  State state() const { return state_; }
  uint32_t segment() const { return segment_; }
  uint32_t segments() const { return segments_; }
  const PolarisQca::Version &version() const { return version_; }

  size_t begin(uint8_t *out, size_t capacity)
  {
    if (state_ != Idle) return 0;
    const size_t size = PolarisQca::versionRequest(out, capacity);
    if (size != 0) state_ = AwaitVersion;
    return size;
  }

  bool acceptVersion(const uint8_t *event, size_t length)
  {
    if (state_ != AwaitVersion ||
        !PolarisQca::parseVersionEvent(event, length, &version_)) {
      state_ = Failed;
      return false;
    }
    state_ = ReadyForSegment;
    return true;
  }

  size_t nextSegment(const uint8_t *file, size_t total,
                     uint8_t *out, size_t capacity)
  {
    if (state_ != ReadyForSegment || file == nullptr || out == nullptr ||
        total == 0 || total > kMaxFileBytes || total != total_) {
      if (state_ == ReadyForSegment) state_ = Failed;
      return 0;
    }
    const size_t offset = static_cast<size_t>(segment_) * PolarisQca::kMaxSegment;
    if (offset >= total_) {
      state_ = Failed;
      return 0;
    }
    const size_t remaining = total_ - offset;
    const size_t length = remaining > PolarisQca::kMaxSegment
        ? PolarisQca::kMaxSegment : remaining;
    const size_t size = PolarisQca::segmentRequest(
        file + offset, length, out, capacity);
    if (size == 0) {
      state_ = Failed;
      return 0;
    }
    state_ = AwaitSegment;
    return size;
  }

  bool startFile(size_t total)
  {
    if (state_ != ReadyForSegment || total == 0 || total > kMaxFileBytes) {
      state_ = Failed;
      return false;
    }
    total_ = total;
    segments_ = static_cast<uint32_t>(
        (total + PolarisQca::kMaxSegment - 1) / PolarisQca::kMaxSegment);
    segment_ = 0;
    return true;
  }

  bool acceptSegmentAck(const uint8_t *event, size_t length)
  {
    if (state_ != AwaitSegment ||
        !PolarisQca::parseSegmentEvent(event, length)) {
      state_ = Failed;
      return false;
    }
    ++segment_;
    state_ = segment_ == segments_ ? Complete : ReadyForSegment;
    return true;
  }

private:
  State state_;
  size_t total_;
  uint32_t segment_;
  uint32_t segments_;
  PolarisQca::Version version_;
};

} // namespace PolarisH4

#endif
