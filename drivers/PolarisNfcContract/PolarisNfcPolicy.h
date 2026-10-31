/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/*
 * Side-effect-free PN54x/NCI resource contract for Xiaomi Polaris.
 *
 * This header only validates board evidence and creates a decision record.
 * It never opens I2C, toggles GPIOs, claims an IRQ, loads NXP firmware, or
 * exposes a secure-element/NFC service.
 */
#ifndef POLARIS_NFC_POLICY_H
#define POLARIS_NFC_POLICY_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum PolarisNfcReason {
    PolarisNfcReasonNone = 0,
    PolarisNfcReasonBoardMismatch = 1,
    PolarisNfcReasonControllerMissing = 2,
    PolarisNfcReasonInvalidBus = 3,
    PolarisNfcReasonInvalidAddress = 4,
    PolarisNfcReasonInvalidIrq = 5,
    PolarisNfcReasonFirmwareIncomplete = 6,
    PolarisNfcReasonHardwareValidationRequired = 7,
};

typedef struct {
    uint8_t board_matches;
    uint8_t controller_present;
    uint8_t bus_present;
    uint8_t address_valid;
    uint8_t irq_present;
    uint8_t firmware_complete;
    uint8_t i2c_bus;
    uint8_t address7;
    uint32_t irq_gpio;
} PolarisNfcEvidence;

typedef struct {
    uint8_t resource_contract_valid;
    uint8_t i2c_writes_allowed;
    uint8_t interrupts_allowed;
    uint8_t firmware_load_allowed;
    uint8_t secure_element_allowed;
    uint32_t reason;
} PolarisNfcPlan;

static inline int polaris_nfc_bus_valid(uint8_t bus)
{
    /* QUPv3 SE3 is the board candidate; reject impossible controller IDs. */
    return bus <= 15U;
}

static inline int polaris_nfc_address_valid(uint8_t address7)
{
    return address7 >= 0x03U && address7 <= 0x77U;
}

static inline int polaris_nfc_irq_valid(uint32_t irq_gpio)
{
    /* GPIO 63 is the Polaris candidate; bound the contract to TLMM GPIOs. */
    return irq_gpio <= 4095U;
}

static inline PolarisNfcPlan
polaris_nfc_make_plan(PolarisNfcEvidence evidence)
{
    PolarisNfcPlan plan = {0, 0, 0, 0, 0, PolarisNfcReasonNone};
    if (!evidence.board_matches) {
        plan.reason = PolarisNfcReasonBoardMismatch;
        return plan;
    }
    if (!evidence.controller_present) {
        plan.reason = PolarisNfcReasonControllerMissing;
        return plan;
    }
    if (!evidence.bus_present || !polaris_nfc_bus_valid(evidence.i2c_bus)) {
        plan.reason = PolarisNfcReasonInvalidBus;
        return plan;
    }
    if (!evidence.address_valid ||
        !polaris_nfc_address_valid(evidence.address7)) {
        plan.reason = PolarisNfcReasonInvalidAddress;
        return plan;
    }
    if (!evidence.irq_present || !polaris_nfc_irq_valid(evidence.irq_gpio)) {
        plan.reason = PolarisNfcReasonInvalidIrq;
        return plan;
    }
    if (!evidence.firmware_complete) {
        plan.reason = PolarisNfcReasonFirmwareIncomplete;
        return plan;
    }

    /* A complete contract still never authorizes live NFC operations. */
    plan.resource_contract_valid = 1;
    plan.reason = PolarisNfcReasonHardwareValidationRequired;
    return plan;
}

#ifdef __cplusplus
}
#endif

#endif
