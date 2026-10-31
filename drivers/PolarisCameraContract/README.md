# PolarisCameraContract

This is a Darwin 23 resource contract for the Polaris camera candidates. It
records CCI/CSIPHY/CSID device-tree evidence and the EDK2 IMX363 candidate
(`0x34`, ID register `0x0016`, expected ID `0x0363`). OV5675 and S5K3M3 remain
candidate names only.

The reference DTB carries only generic `qcom,cam-sensor` nodes; the sensor part
number lives in vendor sensormodule blobs, not in the DT. The service therefore
scans node names and `compatible` strings for a sensor identity and publishes
`polaris-camera-sensor-kind` plus `polaris-camera-sensor-identity-confirmed=false`
and `polaris-camera-sensor-address-confirmed=false`. It never assumes the
fitted sensor is an IMX363.

The fail-closed reasons are distinct so an absent node is never reported as a
malformed one: `MissingSensor` (no sensor node at all), `SensorIdentityRequired`
(node exists but identity unknown, or the ID register was never read),
`InvalidSensorAddress` (address out of the 7-bit range), `MissingCci`,
`MissingCsi`, `FirmwareIncomplete`.

The service is disabled unless `polaris-camera-probe=1` is present. It never
powers a sensor, drives clocks or GPIOs, reads CCI, starts CSIPHY/CSID, creates
DMA, loads CAMX/ICP/tuning firmware, or publishes a camera data path. It keeps
`darwin-driver-ready=false` until a real Polaris temporary boot validates the
complete camera stack.
