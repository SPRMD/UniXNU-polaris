#include <assert.h>
#include <stdio.h>

#include "../drivers/PolarisPmicInput/PolarisPmicInputProtocol.h"

using namespace PolarisPmicInput;

int main()
{
  ReadRequest plan[5] = {};
  assert(makeObserverPlan(plan, 5) == 5);
  assert(plan[0].peripheral == kPonPeripheral && plan[0].reg == 0x04);
  assert(plan[2].peripheral == kFuelGaugePeripheral && plan[2].count == 3);
  assert(!allowRead(kPonPeripheral, 0x00, 1));
  assert(!allowRead(kPonPeripheral, 0x04, 9));

  const uint8_t revA[] = {1, 0x51, 0x15};
  const uint8_t revB[] = {1, 0x51, 0x15};
  assert(identifyRevision(revA, revB) == kEarly);

  KeyLevels keys = {};
  assert(decodeKeyLevels(0x01, 0x00, &keys));
  assert(keys.power && keys.volumeUp && !keys.volumeDown);
  assert(decodeKeyLevels(0x00, 0x01, &keys));
  assert(!keys.power && !keys.volumeUp && !keys.volumeDown);

  ObserverSnapshot sample = {kV2, 0, 0, 128, 0x20, 0x0e,
                             0x10, 0x00, 0x40, 0x04};
  BatterySample battery = {};
  assert(decodeBattery(sample, &battery));
  assert(battery.percent >= 1 && battery.percent <= 100);
  assert(battery.millivolts > 0);
  printf("PASS PMIC input codec: plan=5 soc=%u mv=%u\n", battery.percent,
         battery.millivolts);
  return 0;
}
