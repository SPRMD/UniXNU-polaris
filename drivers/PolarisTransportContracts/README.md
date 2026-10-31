# PolarisTransportContracts

This component brings the portable protocol cores needed by the next Polaris
hardware stages into the Darwin 23 build:

- WCN399x QCA H4 command/event framing, version and firmware-segment framing;
  `QcaFirmwareSession` provides a bounded, acknowledgement-gated sequence for
  version discovery and multi-segment firmware transfer without owning a UART
  or reading a firmware file;
- WLFW board-data QMI TLV construction;
- PN54x/NCI 1.x `CORE_RESET`/`CORE_INIT` framing;
- Qualcomm CCI sensor read command encoding and bounded FIFO decoding.
- A deterministic codec self-test covering the H4 framing and four protocol
  families.

The IOKit service is diagnostic only and is disabled unless the kernel command
line contains `polaris-transport-probe=1`. It publishes that the protocol
cores are linked, but it does not map registers, open UART/I2C/CCI, enable
clocks or regulators, load firmware, allocate DMA, or register a network,
Bluetooth, NFC, or camera data path. On a probe-enabled boot it runs the
in-memory codec vectors and publishes their bitmask; `darwin-driver-ready`
therefore remains false even when all vectors pass. The local Polaris research
tree supplied the protocol shapes; Android or Windows binaries are not used as
Darwin drivers.
