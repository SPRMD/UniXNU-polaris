# PolarisNfcContract

This is a Darwin 23 resource contract for the Polaris PN553/PN54x NFC
candidate. It records the board evidence (`QUPv3 SE3`, I2C address `0x28` and
candidate IRQ GPIO `63`) and counts matching device-tree nodes.

The service is disabled unless `polaris-nfc-probe=1` is present. It never opens
I2C, sends NCI frames, toggles reset or clock GPIOs, claims an interrupt, loads
NXP firmware, creates DMA, or publishes a secure-element/NFC data path. The
policy remains `darwin-driver-ready=false` and the runtime gate stays closed
until a real Polaris temporary boot proves the transport and recovery path.
