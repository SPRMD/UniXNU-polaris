/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <assert.h>
#include <stddef.h>
#include "../drivers/PolarisGeniI2c/PolarisGeniI2cResources.h"

int main(void)
{
    PolarisGeniI2cResource nfc = {};
    PolarisGeniI2cResource touch = {};
    assert(polaris_geni_i2c_resource(PolarisGeniI2cNfc, &nfc));
    assert(nfc.base == 0x88c000ULL && nfc.size == 0x4000 && nfc.irq == 604);
    assert(nfc.address7 == 0x28 && nfc.irq_gpio == 63 && nfc.reset_gpio == 12);
    assert(polaris_geni_i2c_resource_valid(&nfc));
    assert(polaris_geni_i2c_resource(PolarisGeniI2cTouch, &touch));
    assert(touch.base == 0xa98000ULL && touch.size == 0x4000 && touch.irq == 359);
    assert(touch.address7 == 0x20 && touch.irq_gpio == 125 && touch.reset_gpio == 99);
    assert(polaris_geni_i2c_resource_valid(&touch));
    assert(!polaris_geni_i2c_resource(0, &touch));
    assert(!polaris_geni_i2c_resource_valid(NULL));
    return 0;
}
