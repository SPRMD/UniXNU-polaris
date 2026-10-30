// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <cassert>
#include <cstdint>
#include <cstring>

#include "../drivers/PolarisTransportContracts/PolarisCciProtocol.h"
#include "../drivers/PolarisTransportContracts/PolarisNci.h"
#include "../drivers/PolarisTransportContracts/PolarisPmicProtocol.h"
#include "../drivers/PolarisTransportContracts/PolarisQcaProtocol.h"
#include "../drivers/PolarisTransportContracts/PolarisWlfwProtocol.h"

static void testQca()
{
  uint8_t request[8] = {};
  assert(PolarisQca::versionRequest(request, sizeof(request)) == 5);
  assert(request[0] == 1 && request[2] == 0xfc && request[4] == 0x19);
  const uint8_t event[] = {4, 0xff, 14, 0, 2, 1, 2, 3, 4, 5, 6, 7, 8,
                           9, 10, 11, 12};
  PolarisQca::Version version = {};
  assert(PolarisQca::parseVersionEvent(event, sizeof(event), &version));
  assert(version.product == 0x04030201 && version.rom == 0x0807 &&
         version.soc == 0x0c0b0a09);
}

static void testNci()
{
  PolarisNci::CoreHandshake handshake;
  uint8_t command[8] = {};
  assert(handshake.nextCommand(command, sizeof(command)) == 4);
  const uint8_t reset[] = {0x40, 0x00, 0x03, 0x00, 0x10, 0x00};
  assert(handshake.acceptResponse(reset, sizeof(reset)));
  assert(handshake.nextCommand(command, sizeof(command)) == 3);
  uint8_t init[20] = {0x40, 0x01, 17, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0,
                      0, 0, 0, 0, 0, 0, 0};
  assert(handshake.acceptResponse(init, sizeof(init)));
  assert(handshake.state() == PolarisNci::CoreHandshake::Ready);
}

static void testCci()
{
  PolarisCCIReadRequest request = {0x1234, 0x20, 2, 2, 1};
  uint32_t words[POLARIS_CCI_READ_WORDS] = {};
  assert(PolarisCCIEncodeRead(&request, words, 5));
  const uint32_t fifo[] = {0x00bbaa00};
  uint8_t result[2] = {};
  assert(PolarisCCIDecodeRead(fifo, 1, result, sizeof(result), 2));
  assert(result[0] == 0xaa && result[1] == 0xbb);

  PolarisCCIReadRequest imx363 = {};
  assert(PolarisCCIImx363Probe(&imx363));
  assert(imx363.registerAddress == POLARIS_IMX363_ID_REGISTER &&
         imx363.slaveAddress7 == POLARIS_IMX363_I2C_ADDRESS &&
         imx363.registerAddressBytes == 2 && imx363.readBytes == 2);
  const uint8_t imx363Id[] = {POLARIS_IMX363_ID_MSB, POLARIS_IMX363_ID_LSB};
  assert(PolarisCCIValidateImx363Id(imx363Id, sizeof(imx363Id)));
  assert(!PolarisCCIValidateImx363Id(imx363Id, 1));
}

static void testWlfw()
{
  uint8_t file[3] = {1, 2, 3};
  uint8_t payload[64] = {};
  const size_t size = PolarisWlfw::bdfRequest(file, sizeof(file), 0, payload,
                                              sizeof(payload));
  assert(size != 0 && payload[0] == 1);
  const uint8_t accepted[] = {2, 4, 0, 0, 0, 0, 0};
  assert(PolarisWlfw::bdfAccepted(accepted, sizeof(accepted)));
}

static void testPmic()
{
  const uint8_t early[] = {1, 0x51, 0x15};
  assert(PolarisPmic::identifyRevision(early, early) == PolarisPmic::Early);
  uint32_t command = 0;
  assert(PolarisPmic::readCommand(0x240, 0x09, 2, &command));
  assert(!PolarisPmic::readCommand(0x240, 0x10, 1, &command));
  PolarisPmic::FuelGaugeSample sample = {};
  assert(PolarisPmic::convertSample(PolarisPmic::V2, 128, 0x34, 0x12,
                                    0, 0, 0x40, 0x04, &sample));
  assert(sample.percent == 50 && sample.millivolts != 0);
  bool power = false, up = false, down = false;
  assert(PolarisPmic::decodeKeyLevels(0x03, 0, &power, &up, &down));
  assert(power && up && down);
}

int main()
{
  testQca();
  testNci();
  testCci();
  testWlfw();
  testPmic();
  return 0;
}
