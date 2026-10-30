// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Bounded Qualcomm CCI read command encoding for camera bring-up.  The
// routines only encode/decode words and never touch CCI, CSIPHY, CSID, PMIC,
// clocks, or sensor power rails.
#ifndef POLARIS_CCI_PROTOCOL_H
#define POLARIS_CCI_PROTOCOL_H

#include <stdint.h>

enum { POLARIS_CCI_READ_WORDS = 5, POLARIS_CCI_MAX_READ = 12 };

struct PolarisCCIReadRequest {
  uint32_t registerAddress;
  uint8_t slaveAddress7;
  uint8_t registerAddressBytes;
  uint8_t readBytes;
  uint8_t retries;
};

/* Polaris board evidence from the EDK2 IMX363 configuration.  These constants
 * describe a bounded probe only; they do not grant ownership of the CCI bus,
 * camera clocks, GPIOs, regulators or CSI blocks. */
enum {
  POLARIS_IMX363_I2C_ADDRESS = 0x34,
  POLARIS_IMX363_ID_REGISTER = 0x0016,
  POLARIS_IMX363_ID_MSB = 0x03,
  POLARIS_IMX363_ID_LSB = 0x63,
  POLARIS_IMX363_PROBE_HZ = 400000,
};

static inline bool PolarisCCIImx363Probe(PolarisCCIReadRequest *request)
{
  if (request == nullptr) return false;
  *request = {POLARIS_IMX363_ID_REGISTER,
              POLARIS_IMX363_I2C_ADDRESS,
              2,
              2,
              2};
  return true;
}

static inline bool PolarisCCIValidateImx363Id(const uint8_t *data,
                                              uint32_t length)
{
  return data != nullptr && length == 2 && data[0] == POLARIS_IMX363_ID_MSB &&
         data[1] == POLARIS_IMX363_ID_LSB;
}

static inline bool PolarisCCIEncodeRead(const PolarisCCIReadRequest *request,
                                        uint32_t *words, uint32_t capacity)
{
  if (request == nullptr || words == nullptr ||
      capacity < POLARIS_CCI_READ_WORDS || request->slaveAddress7 > 0x7f ||
      request->registerAddressBytes < 1 || request->registerAddressBytes > 3 ||
      request->readBytes < 1 || request->readBytes > POLARIS_CCI_MAX_READ ||
      request->retries > 3 ||
      (request->registerAddress >> (request->registerAddressBytes * 8)) != 0) {
    return false;
  }
  uint32_t addressWord = 11u | ((uint32_t)request->registerAddressBytes << 4);
  for (uint32_t i = 0; i < request->registerAddressBytes; ++i) {
    addressWord |= ((request->registerAddress >> (8 * i)) & 0xffu) <<
                   (8 * (request->registerAddressBytes - i));
  }
  const uint32_t encoded[POLARIS_CCI_READ_WORDS] = {
      1u | ((uint32_t)request->slaveAddress7 << 4) |
          ((uint32_t)request->retries << 16),
      6u,
      addressWord,
      10u | ((uint32_t)request->readBytes << 4),
      7u,
  };
  for (unsigned i = 0; i < POLARIS_CCI_READ_WORDS; ++i) words[i] = encoded[i];
  return true;
}

static inline bool PolarisCCIDecodeRead(const uint32_t *words,
                                        uint32_t wordCount, uint8_t *data,
                                        uint32_t dataCapacity,
                                        uint32_t requestedBytes)
{
  if (words == nullptr || data == nullptr || requestedBytes < 1 ||
      requestedBytes > POLARIS_CCI_MAX_READ || dataCapacity < requestedBytes ||
      wordCount != requestedBytes / 4u + 1u) return false;
  uint8_t result[POLARIS_CCI_MAX_READ];
  for (uint32_t i = 0; i < requestedBytes; ++i) {
    const uint32_t sourceByte = i + 1u;
    result[i] = (uint8_t)(words[sourceByte / 4u] >>
                          (8u * (sourceByte % 4u)));
  }
  for (uint32_t i = 0; i < requestedBytes; ++i) data[i] = result[i];
  return true;
}

#endif
