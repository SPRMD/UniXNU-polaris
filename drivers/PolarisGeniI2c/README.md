# PolarisGeniI2c

This directory contains a local, board-independent Qualcomm GENI I2C FIFO
state machine for the Polaris port. It is derived from the BSD-2-Clause-Patent
package/GeniI2c.h and package/GeniI2c.c files in the UniXNU-sheng
repository at revision 08cde20edc3254ed6f7df8d0f5384fb887786e8f.

The core only consumes register read/write callbacks supplied by a board
transport. It supports the GENI I2C firmware protocol, bounded FIFO transfers,
held-stop register reads, NACK/error reporting, and cancel-then-abort timeout
recovery. It does not map MMIO, select clocks, configure GPIOs, claim an IRQ,
load firmware, allocate DMA, or access a phone by itself.

A Polaris consumer must first prove the selected QUPv3 serial engine, firmware
protocol, clock/pin ownership, interrupt route, and power state. Until that
proof and a temporary boot test exist, this component remains a portable build
and host-test input only. It is deliberately not registered in the default
kernel configuration and cannot set any darwin-driver-ready contract by
itself.

The original source comments and SPDX identifier are retained. No Linux or
Android driver binary is used.


