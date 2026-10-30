# Polaris protocol layer

This directory contains bounded, transport-independent protocol code for the
hardware that the MIX 2S port must eventually expose to Darwin:

- WCN3998 H4 and WLFW board-data framing;
- NCI 1.x core reset/init for the PN553-class NFC controller;
- Qualcomm CCI register-read command encoding for camera sensors;
- PMI8998 battery revision, fuel-gauge conversion, and a narrow SPMI read
  whitelist; and
- the PMIC power/volume key level mapping.

The Python module is an executable host reference. It performs no I2C, UART,
SPMI, GPIO, DMA, MMIO, firmware loading, or IOKit registration. The Darwin
driver still needs a board-owned transport, interrupt and power-sequencing
implementation, followed by a user-approved temporary Polaris boot. Android
firmware and vendor libraries are evidence inputs only and are not loaded by
this layer.

The layouts follow the local Polaris XNU research and the BSD-2-Clause-Patent
UniXNU-sheng protocol references. This tree keeps the code as a new bounded
implementation instead of copying a Linux or Android driver.
