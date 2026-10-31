// SPDX-License-Identifier: BSD-2-Clause-Patent
// Side-effect-free codec vectors for the Polaris transport protocol cores.
#ifndef POLARIS_PROTOCOL_SELF_TEST_H
#define POLARIS_PROTOCOL_SELF_TEST_H

#include <stdint.h>
#include "PolarisCciProtocol.h"
#include "PolarisH4Protocol.h"
#include "PolarisNci.h"
#include "PolarisQcaProtocol.h"
#include "PolarisWlfwProtocol.h"

namespace PolarisTransportSelfTest {
enum : uint32_t { kQcaH4 = 1u << 0, kNci = 1u << 1, kCci = 1u << 2,
                  kWlfw = 1u << 3, kH4Framing = 1u << 4,
                  kAll = kQcaH4 | kNci | kCci | kWlfw | kH4Framing };
struct Result { uint32_t passed; uint32_t failed; };
static inline bool qca()
{
  uint8_t request[8] = {};
  if (PolarisQca::versionRequest(request, sizeof(request)) != 5 || request[0] != 1 ||
      request[2] != 0xfc || request[4] != 0x19) return false;
  const uint8_t event[] = {4, 0xff, 14, 0, 2, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};
  PolarisQca::Version version = {};
  return PolarisQca::parseVersionEvent(event, sizeof(event), &version) &&
         version.product == 0x04030201u && version.patch == 0x0605u &&
         version.rom == 0x0807u && version.soc == 0x0c0b0a09u;
}
static inline bool qcaFirmwareSession()
{
  uint8_t request[PolarisH4::kMaxPacket] = {};
  PolarisH4::QcaFirmwareSession session;
  if (session.begin(request, sizeof(request)) != 5 ||
      session.state() != PolarisH4::QcaFirmwareSession::AwaitVersion) {
    return false;
  }
  const uint8_t versionEvent[] = {
      4, 0xff, 14, 0, 2, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};
  if (!session.acceptVersion(versionEvent, sizeof(versionEvent)) ||
      session.state() != PolarisH4::QcaFirmwareSession::ReadyForSegment ||
      session.version().rom != 0x0807u) {
    return false;
  }
  const uint8_t file[PolarisQca::kMaxSegment + 1] = {};
  if (!session.startFile(sizeof(file)) || session.segments() != 2 ||
      session.segment() != 0) {
    return false;
  }
  if (session.nextSegment(file, sizeof(file), request, sizeof(request)) !=
          PolarisQca::kMaxSegment + 6 ||
      session.state() != PolarisH4::QcaFirmwareSession::AwaitSegment ||
      request[4] != 0x1e || request[5] != PolarisQca::kMaxSegment) {
    return false;
  }
  const uint8_t accepted[] = {4, 0xff, 3, 0, 4, 0};
  if (!session.acceptSegmentAck(accepted, sizeof(accepted)) ||
      session.segment() != 1 ||
      session.state() != PolarisH4::QcaFirmwareSession::ReadyForSegment) {
    return false;
  }
  if (session.nextSegment(file, sizeof(file), request, sizeof(request)) != 7 ||
      session.state() != PolarisH4::QcaFirmwareSession::AwaitSegment ||
      request[5] != 1 || request[6] != 0) {
    return false;
  }
  if (!session.acceptSegmentAck(accepted, sizeof(accepted)) ||
      session.segment() != 2 ||
      session.state() != PolarisH4::QcaFirmwareSession::Complete ||
      session.nextSegment(file, sizeof(file), request, sizeof(request)) != 0) {
    return false;
  }
  session.reset();
  if (session.startFile(PolarisH4::QcaFirmwareSession::kMaxFileBytes + 1) ||
      session.state() != PolarisH4::QcaFirmwareSession::Failed) {
    return false;
  }
  return true;
}
static inline bool nci()
{
  PolarisNci::CoreHandshake handshake;
  uint8_t command[8] = {};
  if (handshake.nextCommand(command, sizeof(command)) != 4 || command[0] != 0x20 ||
      command[2] != 1 || command[3] != 0) return false;
  const uint8_t reset[] = {0x40, 0x00, 0x03, 0x00, 0x10, 0x00};
  if (!handshake.acceptResponse(reset, sizeof(reset)) || handshake.nextCommand(command, sizeof(command)) != 3) return false;
  const uint8_t init[20] = {0x40, 0x01, 17, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
  return handshake.acceptResponse(init, sizeof(init)) && handshake.state() == PolarisNci::CoreHandshake::Ready;
}
static inline bool cci()
{
  PolarisCCIReadRequest request = {};
  uint32_t words[POLARIS_CCI_READ_WORDS] = {};
  if (!PolarisCCIImx363Probe(&request) || !PolarisCCIEncodeRead(&request, words, POLARIS_CCI_READ_WORDS)) return false;
  const uint32_t fifo[] = {0x00bbaa00u};
  uint8_t id[2] = {};
  const uint8_t expected[] = {POLARIS_IMX363_ID_MSB, POLARIS_IMX363_ID_LSB};
  return PolarisCCIDecodeRead(fifo, 1, id, sizeof(id), 2) && PolarisCCIValidateImx363Id(expected, sizeof(expected)) && id[0] == 0xaa && id[1] == 0xbb;
}
static inline bool wlfw()
{
  const uint8_t file[] = {0xa5, 0x5a, 0x01};
  uint8_t request[64] = {};
  const size_t size = PolarisWlfw::bdfRequest(file, sizeof(file), 0, request, sizeof(request));
  const uint8_t accepted[] = {2, 4, 0, 0, 0, 0, 0};
  return size == sizeof(file) + PolarisWlfw::kOverhead && request[0] == 1 && PolarisWlfw::bdfAccepted(accepted, sizeof(accepted));
}
static inline bool h4Framing()
{
  const uint8_t params[] = {0x19};
  uint8_t command[8] = {};
  if (PolarisH4::command(0xfc00, params, sizeof(params), command,
                         sizeof(command)) != 5 ||
      command[0] != PolarisH4::kCommand || command[1] != 0 ||
      command[2] != 0xfc || command[3] != 1 || command[4] != 0x19) {
    return false;
  }
  PolarisH4::Reader reader = {};
  reader.reset();
  const uint8_t event[] = {0x04, 0xff, 0x00};
  int result = 0;
  for (uint8_t byte : event) result = reader.feed(byte);
  return result == 1 && PolarisH4::isEvent(reader);
}
static inline Result run()
{
  Result result = {};
  if (qca() && qcaFirmwareSession()) result.passed |= kQcaH4;
  else result.failed |= kQcaH4;
  if (nci()) result.passed |= kNci; else result.failed |= kNci;
  if (cci()) result.passed |= kCci; else result.failed |= kCci;
  if (wlfw()) result.passed |= kWlfw; else result.failed |= kWlfw;
  if (h4Framing()) result.passed |= kH4Framing; else result.failed |= kH4Framing;
  return result;
}
} // namespace PolarisTransportSelfTest
#endif
