// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Bounded NCI 1.x control framing for the Polaris PN54x candidate.  This is a
// protocol core only: it performs no I2C, GPIO, IRQ, firmware, or NFC daemon
// operation.
#ifndef POLARIS_NCI_H
#define POLARIS_NCI_H

#include <stddef.h>
#include <stdint.h>

namespace PolarisNci {

static const size_t kHeaderSize = 3;
static const size_t kMaxFrameSize = kHeaderSize + 255;

struct Packet {
  uint8_t type;
  uint8_t group;
  uint8_t opcode;
  uint8_t length;
  const uint8_t *payload;
};

static inline bool parseControl(const uint8_t *data, size_t size, Packet *out)
{
  if (data == nullptr || out == nullptr || size < kHeaderSize ||
      size > kMaxFrameSize) return false;
  const uint8_t type = (uint8_t)((data[0] >> 5) & 7U);
  if ((data[0] & 0x10U) != 0 || type < 1 || type > 3 ||
      (data[1] & 0xc0U) != 0 || size != kHeaderSize + (size_t)data[2]) {
    return false;
  }
  out->type = type;
  out->group = data[0] & 0x0fU;
  out->opcode = data[1] & 0x3fU;
  out->length = data[2];
  out->payload = data + kHeaderSize;
  return true;
}

class CoreHandshake {
public:
  enum State { Idle, AwaitReset, SendInit, AwaitInit, Ready, Failed };

  CoreHandshake() : state_(Idle) {}
  State state() const { return state_; }
  void reset() { state_ = Idle; }
  void timeout() { if (state_ != Ready) state_ = Failed; }

  size_t nextCommand(uint8_t *out, size_t capacity)
  {
    if (out == nullptr) return 0;
    if (state_ == Idle && capacity >= 4) {
      out[0] = 0x20; out[1] = 0x00; out[2] = 0x01; out[3] = 0x00;
      state_ = AwaitReset;
      return 4;
    }
    if (state_ == SendInit && capacity >= 3) {
      out[0] = 0x20; out[1] = 0x01; out[2] = 0x00;
      state_ = AwaitInit;
      return 3;
    }
    return 0;
  }

  bool acceptResponse(const uint8_t *data, size_t size)
  {
    Packet packet = {};
    if ((state_ != AwaitReset && state_ != AwaitInit) ||
        !parseControl(data, size, &packet) || packet.type != 2 ||
        packet.group != 0 || packet.length == 0 || packet.payload[0] != 0) {
      state_ = Failed;
      return false;
    }
    if (state_ == AwaitReset) {
      if (packet.opcode != 0 || packet.length != 3 ||
          (packet.payload[1] >> 4) != 1) {
        state_ = Failed;
        return false;
      }
      state_ = SendInit;
      return true;
    }
    if (packet.opcode != 1 || packet.length < 17 ||
        packet.length != (size_t)17 + packet.payload[5]) {
      state_ = Failed;
      return false;
    }
    state_ = Ready;
    return true;
  }

private:
  State state_;
};

} // namespace PolarisNci

#endif
