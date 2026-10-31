/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Board resource facts for the SDM845 Polaris GENI I2C engines. */
#ifndef POLARIS_GENI_I2C_RESOURCES_H
#define POLARIS_GENI_I2C_RESOURCES_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum PolarisGeniI2cPeripheral {
    PolarisGeniI2cNfc = 1,
    PolarisGeniI2cTouch = 2,
};

typedef struct {
    uint64_t base;
    uint32_t size;
    uint32_t irq;
    uint8_t address7;
    uint16_t irq_gpio;
    uint16_t reset_gpio;
    uint8_t bus_index;
} PolarisGeniI2cResource;

/* Values are from the Polaris SDM845 device tree, not guessed runtime state. */
static inline int polaris_geni_i2c_resource(
    enum PolarisGeniI2cPeripheral peripheral,
    PolarisGeniI2cResource *out)
{
    if (out == 0) return 0;
    *out = (PolarisGeniI2cResource){0, 0, 0, 0, 0xffff, 0xffff, 0};
    switch (peripheral) {
    case PolarisGeniI2cNfc:
        /* qupv3_se3_i2c: i2c@88c000, GIC SPI 604, PN54x 0x28, GPIO63 IRQ. */
        *out = (PolarisGeniI2cResource){0x0088c000ULL, 0x4000, 604,
                                        0x28, 63, 12, 3};
        return 1;
    case PolarisGeniI2cTouch:
        /* qupv3_se14_i2c: i2c@a98000, GIC SPI 359, S3330 0x20,
         * GPIO125 IRQ and GPIO99 reset. */
        *out = (PolarisGeniI2cResource){0x00a98000ULL, 0x4000, 359,
                                        0x20, 125, 99, 14};
        return 1;
    default:
        return 0;
    }
}

static inline int polaris_geni_i2c_resource_valid(
    const PolarisGeniI2cResource *resource)
{
    return resource != 0 && resource->base != 0 && resource->size == 0x4000 &&
           resource->irq != 0 && resource->address7 >= 0x03 &&
           resource->address7 <= 0x77 && resource->bus_index <= 15;
}

#ifdef __cplusplus
}
#endif

#endif
