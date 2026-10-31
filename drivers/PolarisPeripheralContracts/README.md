# Polaris peripheral contracts

This Darwin 23 archive is the board-specific integration point for the
Polaris WCN3998/WCN3990 wireless family, PN54x/NCI NFC candidate and
IMX363/CCI camera candidate. It walks the supplied device tree, publishes the
candidate transport and firmware names, and runs the bounded QCA, WLFW, NCI and
CCI codec self-tests already present in `PolarisTransportContracts`.

It performs no MMIO, interrupt registration, GPIO or regulator operation,
firmware download, DMA allocation, network registration, camera stream, or NFC
transaction. It is enabled only by `polaris-peripheral-probe=1`; the future
hardware backends have separate gates (`polaris-wireless-runtime=1`,
`polaris-nfc-runtime=1`, and `polaris-camera-runtime=1`). The service therefore
does not claim that Wi-Fi, Bluetooth, NFC or camera work on a phone.
