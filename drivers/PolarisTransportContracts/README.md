# PolarisTransportContracts

This component brings the portable protocol cores needed by the next Polaris
hardware stages into the Darwin 23 build:

- WCN399x QCA H4 version and firmware-segment framing;
- WLFW board-data QMI TLV construction;
- PN54x/NCI 1.x `CORE_RESET`/`CORE_INIT` framing;
- Qualcomm CCI sensor read command encoding and bounded FIFO decoding.

The IOKit service is diagnostic only and is disabled unless the kernel command
line contains `polaris-transport-probe=1`. It publishes that the protocol
cores are linked, but it does not map registers, open UART/I2C/CCI, enable
clocks or regulators, load firmware, allocate DMA, or register a network,
Bluetooth, NFC, or camera data path. `darwin-driver-ready` therefore remains
false. The local Polaris research tree supplied the protocol shapes; Android
or Windows binaries are not used as Darwin drivers.
