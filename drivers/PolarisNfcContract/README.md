# PolarisNfcContract

This is a Darwin 23 resource contract for the Polaris PN553/PN54x NFC
candidate. It counts matching device-tree nodes and reads the candidate's
`reg` (7-bit I2C address) and `interrupts` (TLMM GPIO) properties directly
from the DT node instead of assuming them.

The documented board candidates (`QUPv3 SE3`, address `0x28`, IRQ GPIO `63`)
are published as candidates only; the observed values are published separately
as `polaris-nfc-i2c-address-observed`, `polaris-nfc-irq-gpio-observed` and the
`*-matches-candidate` flags. The QUPv3 SE number is not parsed from the DT, so
`polaris-nfc-i2c-bus-source` records that limitation explicitly.

If the node is missing, not under an I2C controller, or its `reg`/`interrupts`
are absent or malformed, `polaris_nfc_make_plan` fails closed with
`ControllerMissing`, `InvalidBus`, `InvalidAddress` or `InvalidIrq` and
`polaris-nfc-resource-contract-valid` stays `0`.

The service is disabled unless `polaris-nfc-probe=1` is present. It never opens
I2C, sends NCI frames, toggles reset or clock GPIOs, claims an interrupt, loads
NXP firmware, creates DMA, or publishes a secure-element/NFC data path. The
policy remains `darwin-driver-ready=false` and the runtime gate stays closed
until a real Polaris temporary boot proves the transport and recovery path.
