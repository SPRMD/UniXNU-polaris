// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Bounded, read-only PMI8998/PM8998 protocol helpers for Polaris power keys
// and battery bring-up.  These functions do not access SPMI or publish an
// IOPMPowerSource; they only validate bytes and convert already captured
// samples.
#ifndef POLARIS_PMIC_PROTOCOL_H
#define POLARIS_PMIC_PROTOCOL_H

#include <stdint.h>

namespace PolarisPmic {

enum Revision { Unknown, Early, V2 };

static inline Revision identifyRevision(const uint8_t *first,
                                        const uint8_t *second)
{
  if (first == nullptr || second == nullptr ||
      first[0] != second[0] || first[1] != second[1] ||
      first[2] != second[2] || first[1] != 0x51 || first[2] != 0x15) {
    return Unknown;
  }
  if (first[0] == 1) return Early;
  if (first[0] == 2) return V2;
  return Unknown;
}

static inline bool decodeWord(Revision revision, uint8_t byte0, uint8_t byte1,
                              uint16_t *out)
{
  if (out == nullptr || (revision != Early && revision != V2)) return false;
  *out = revision == Early ? (uint16_t)(((uint16_t)byte0 << 8) | byte1)
                           : (uint16_t)(((uint16_t)byte1 << 8) | byte0);
  return true;
}

static inline unsigned conservativeSoc(uint8_t raw)
{
  if (raw == 0) return 0;
  if (raw == 255) return 100;
  return (((unsigned)raw - 1U) * 98U + 126U) / 253U + 1U;
}

static inline bool permittedRead(uint16_t peripheral, uint8_t reg,
                                 unsigned count)
{
  if (count == 0 || count > 8 || (unsigned)reg + count > 256) return false;
  if (peripheral == 0x008 && count == 1)
    return reg == 0x04 || reg == 0x05 || reg == 0x10;
  if (peripheral == 0x0c5 && count == 1)
    return reg == 0x04 || reg == 0x05 || reg == 0x10 || reg == 0x40 ||
           reg == 0x42 || reg == 0x46;
  if (peripheral == 0x201) return reg == 0x03 && count == 3;
  if (peripheral == 0x240)
    return (reg == 0x05 && count == 1) || (reg == 0x09 && count == 2);
  if (peripheral == 0x241)
    return (reg == 0x05 && count == 1) ||
           (count == 2 && (reg == 0x50 || reg == 0xa0 || reg == 0xa2));
  return false;
}

static inline bool readCommand(uint16_t peripheral, uint8_t reg,
                               unsigned count, uint32_t *out)
{
  if (out == nullptr || !permittedRead(peripheral, reg, count)) return false;
  *out = (1U << 27) | ((uint32_t)reg << 4) | (count - 1U);
  return true;
}

struct FuelGaugeSample {
  unsigned percent;
  unsigned millivolts;
  int currentMicroamps;
  int temperatureDeciCelsius;
};

static inline bool convertSample(Revision revision, uint8_t soc,
                                 uint8_t voltage0, uint8_t voltage1,
                                 uint8_t current0, uint8_t current1,
                                 uint8_t temperature0, uint8_t temperature1,
                                 FuelGaugeSample *out)
{
  if (out == nullptr) return false;
  uint16_t voltage = 0, current = 0;
  if (!decodeWord(revision, voltage0, voltage1, &voltage) ||
      !decodeWord(revision, current0, current1, &current)) return false;
  const int signedCurrent = current & 0x8000U ? (int)current - 65536 : current;
  const unsigned tempRaw = ((unsigned)(temperature1 & 7U) << 8) | temperature0;
  out->percent = conservativeSoc(soc);
  out->millivolts = (unsigned)(((uint64_t)voltage * 122070ULL) / 1000000ULL);
  out->currentMicroamps = (int)(((int64_t)signedCurrent * 488281LL) / 1000LL);
  out->temperatureDeciCelsius = ((int)((tempRaw + 2U) / 4U) - 273) * 10;
  return true;
}

static inline bool decodeKeyLevels(uint8_t ponStatus, uint8_t gpioStatus,
                                   bool *power, bool *volumeUp,
                                   bool *volumeDown)
{
  if (power == nullptr || volumeUp == nullptr || volumeDown == nullptr) {
    return false;
  }
  *power = (ponStatus & 0x01U) != 0;
  *volumeUp = (gpioStatus & 0x01U) == 0; /* active-low PMIC GPIO6 */
  *volumeDown = (ponStatus & 0x02U) != 0;
  return true;
}

} // namespace PolarisPmic

#endif
