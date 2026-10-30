# Polaris WOA facts used by the UniXNU port

The local checkout of `n00b69/woa-polaris` is pinned at commit
`b32b5fb9a9952b499c4c1d5c38f39a7733244040` (2026-08-26). Its `guide/status.md`
reports working Windows paths for battery, Bluetooth, brightness, display,
GPU, touchscreen, UFS, Wi-Fi, USB, accelerometer, GPS, gyroscope, light and
proximity sensors, plus NFC tag reads. Audio, camera and fingerprint remain
unimplemented in that project; its GPU entry also says there is no x64
acceleration.

These entries are hardware and resource evidence only. A Windows driver or an
Android vendor binary cannot be loaded as a Darwin kernel extension. The WOA
tree does not provide an Apple IOKit provider, a Darwin power-management
contract, an iOS trust chain, or a Metal userspace stack. Therefore the Polaris
hardware contract keeps every corresponding UniXNU subsystem disabled until a
Darwin implementation passes a controlled temporary boot.

Useful facts to carry into driver design:

| WOA result | UniXNU use | Current gate |
| --- | --- | --- |
| UFS works | SDM845 UFS resource and reset/power sequencing are plausible inputs for `ShengUfs` | read-only probe only |
| Display and brightness work | MDSS panel/backlight resources can guide a future provider | GOP handoff only |
| Touchscreen works | Synaptics S3330/I2C candidate can guide an IOHID service | disabled |
| GPU works without x64 acceleration | Adreno 630 firmware/resource names are useful for GMU research | disabled |
| Wi-Fi and Bluetooth work | WCN3998 power/transport/firmware extraction is worth investigating | disabled |
| NFC tags work | PN54x/NCI GPIO and I2C candidates are useful | disabled |
| Camera does not work | no working WOA camera implementation to reuse | disabled |

No binary from the WOA checkout is copied into this repository or an image.
The exact private firmware inputs are tracked only by
`research/polaris-firmware-contract.json`, which records SHA-256 values where
known and deliberately reports `darwin_load_allowed=false`.
