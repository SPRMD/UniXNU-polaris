// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Transport-independent PMI8998/PM8998 observer contracts for Polaris.
// These helpers only validate a bounded observation and build a read-only
// request plan. They do not access SPMI, GPIO, interrupts or IOKit services.
#ifndef POLARIS_PMIC_INPUT_PROTOCOL_H
#define POLARIS_PMIC_INPUT_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

namespace PolarisPmicInput {

enum Revision : uint8_t { kUnknown = 0, kEarly = 1, kV2 = 2 };

enum : uint16_t {
  kPonPeripheral = 0x008,
  kGpioPeripheral = 0x0c5,
  kFuelGaugePeripheral = 0x201,
  kChargerPeripheral = 0x240,
  kFuelGaugeAuxPeripheral = 0x241,
};

struct ReadRequest {
  uint16_t peripheral;
  uint8_t reg;
  uint8_t count;
  uint32_t command;
};

struct KeyLevels {
  bool power;
  bool volumeUp;
  bool volumeDown;
};

struct BatterySample {
  unsigned percent;
  unsigned millivolts;
  int currentMicroamps;
  int temperatureDeciCelsius;
};

struct ObserverSnapshot {
  Revision revision;
  uint8_t ponStatus;
  uint8_t gpioStatus;
  uint8_t soc;
  uint8_t voltage0;
  uint8_t voltage1;
  uint8_t current0;
  uint8_t current1;
  uint8_t temperature0;
  uint8_t temperature1;
};

static inline Revision identifyRevision(const uint8_t *first,
                                        const uint8_t *second)
{
  if (first == nullptr || second == nullptr || first[0] != second[0] ||
      first[1] != 0x51 || first[2] != 0x15 ||
      second[1] != 0x51 || second[2] != 0x15) {
    return kUnknown;
  }
  if (first[0] == 1) return kEarly;
  if (first[0] == 2) return kV2;
  return kUnknown;
}

static inline bool allowRead(uint16_t peripheral, uint8_t reg,
                             unsigned count)
{
  if (count == 0 || count > 8 || static_cast<unsigned>(reg) + count > 256)
    return false;
  if (peripheral == kPonPeripheral && count == 1)
    return reg == 0x04 || reg == 0x05 || reg == 0x10;
  if (peripheral == kGpioPeripheral && count == 1)
    return reg == 0x04 || reg == 0x05 || reg == 0x10 || reg == 0x40 ||
           reg == 0x42 || reg == 0x46;
  if (peripheral == kFuelGaugePeripheral) return reg == 0x03 && count == 3;
  if (peripheral == kChargerPeripheral)
    return (reg == 0x05 && count == 1) || (reg == 0x09 && count == 2);
  if (peripheral == kFuelGaugeAuxPeripheral)
    return (reg == 0x05 && count == 1) ||
           (count == 2 && (reg == 0x50 || reg == 0xa0 || reg == 0xa2));
  return false;
}

static inline bool makeReadRequest(uint16_t peripheral, uint8_t reg,
                                   unsigned count, ReadRequest *out)
{
  if (out == nullptr || !allowRead(peripheral, reg, count)) return false;
  out->peripheral = peripheral;
  out->reg = reg;
  out->count = static_cast<uint8_t>(count);
  // Qualcomm SPMI observer command shape used by the Polaris evidence. The
  // service never submits this word; it is a bounded transport contract.
  out->command = (1U << 27) | (static_cast<uint32_t>(reg) << 4) |
                 static_cast<uint32_t>(count - 1);
  return true;
}

static inline size_t makeObserverPlan(ReadRequest *out, size_t capacity)
{
  if (out == nullptr || capacity < 5) return 0;
  const struct {
    uint16_t peripheral;
    uint8_t reg;
    uint8_t count;
  } plan[] = {
      {kPonPeripheral, 0x04, 1},
      {kGpioPeripheral, 0x04, 1},
      {kFuelGaugePeripheral, 0x03, 3},
      {kChargerPeripheral, 0x05, 1},
      {kFuelGaugeAuxPeripheral, 0x05, 1},
  };
  for (size_t i = 0; i < sizeof(plan) / sizeof(plan[0]); ++i) {
    if (!makeReadRequest(plan[i].peripheral, plan[i].reg, plan[i].count,
                         &out[i]))
      return 0;
  }
  return sizeof(plan) / sizeof(plan[0]);
}

static inline unsigned conservativeSoc(uint8_t raw)
{
  if (raw == 0) return 0;
  if (raw == 255) return 100;
  return (((static_cast<unsigned>(raw) - 1U) * 98U + 126U) / 253U) + 1U;
}

static inline bool decodeKeyLevels(uint8_t ponStatus, uint8_t gpioStatus,
                                   KeyLevels *out)
{
  if (out == nullptr) return false;
  out->power = (ponStatus & 0x01U) != 0;
  out->volumeUp = (gpioStatus & 0x01U) == 0; // candidate active-low PMIC GPIO6
  out->volumeDown = (ponStatus & 0x02U) != 0;
  return true;
}

static inline bool decodeWord(Revision revision, uint8_t byte0, uint8_t byte1,
                              uint16_t *out)
{
  if (out == nullptr || (revision != kEarly && revision != kV2)) return false;
  *out = revision == kEarly
             ? static_cast<uint16_t>((static_cast<uint16_t>(byte0) << 8) |
                                     byte1)
             : static_cast<uint16_t>((static_cast<uint16_t>(byte1) << 8) |
                                     byte0);
  return true;
}

static inline bool decodeBattery(const ObserverSnapshot &snapshot,
                                 BatterySample *out)
{
  if (out == nullptr) return false;
  uint16_t voltage = 0, current = 0;
  if (!decodeWord(snapshot.revision, snapshot.voltage0, snapshot.voltage1,
                  &voltage) ||
      !decodeWord(snapshot.revision, snapshot.current0, snapshot.current1,
                  &current))
    return false;
  const int signedCurrent = (current & 0x8000U)
                               ? static_cast<int>(current) - 65536
                               : static_cast<int>(current);
  const unsigned tempRaw =
      (static_cast<unsigned>(snapshot.temperature1 & 7U) << 8) |
      snapshot.temperature0;
  out->percent = conservativeSoc(snapshot.soc);
  out->millivolts = static_cast<unsigned>(
      (static_cast<uint64_t>(voltage) * 122070ULL) / 1000000ULL);
  out->currentMicroamps = static_cast<int>(
      (static_cast<int64_t>(signedCurrent) * 488281LL) / 1000LL);
  out->temperatureDeciCelsius =
      (static_cast<int>((tempRaw + 2U) / 4U) - 273) * 10;
  return true;
}

} // namespace PolarisPmicInput

#endif
