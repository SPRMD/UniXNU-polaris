# PolarisCameraContract

This is a Darwin 23 resource contract for the Polaris camera candidates. It
records CCI/CSIPHY/CSID device-tree evidence and the EDK2 IMX363 candidate
(`0x34`, ID register `0x0016`, expected ID `0x0363`). OV5675 and S5K3M3 remain
candidate names only.

The service is disabled unless `polaris-camera-probe=1` is present. It never
powers a sensor, drives clocks or GPIOs, reads CCI, starts CSIPHY/CSID, creates
DMA, loads CAMX/ICP/tuning firmware, or publishes a camera data path. It keeps
`darwin-driver-ready=false` until a real Polaris temporary boot validates the
complete camera stack.
