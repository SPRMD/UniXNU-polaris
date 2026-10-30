# PolarisBoardProbe

`PolarisBoardProbe` is a board-resource inventory service for the SDM845
Xiaomi Mi MIX 2S port. It reads only device-tree properties published by the
`arm-io` nub and records which known Polaris resource nodes are present. It
does not map registers, enable clocks, change GPIO state, claim interrupts,
touch UFS, or load firmware.

The service is opt-in. It is inert unless the kernel command line contains
`polaris-board-probe=1`. This makes it suitable for a temporary diagnostic
payload while the real UFS, display, touch, GPU, wireless, camera and power
drivers are still being qualified against Darwin 23.

The resulting IORegistry service exposes counters such as
`polaris-board-ufs-present`, `polaris-board-gpu-present`, and
`polaris-board-display-present`, plus `polaris-board-mmio-performed=false`.
These are inventory facts, not proof that a driver works on hardware.
