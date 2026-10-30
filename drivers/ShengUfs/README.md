# SDM845 UFS probe for Polaris

This directory is the SDM845-specific, read-only UFS probe carried from the
local `UniXNU-judyln` Polaris bring-up. It matches the Polaris UFSHCI window
(`0x01d84000/0x2500`, SPI 265) and the SDM845 GCC clock registers recorded in
the stock DTB.

The source is linked only when `CONFIG_XNU_NATIVE_UFS=y`. It is **default-off
at runtime**: the driver returns without mapping UFS unless the explicit
`native-ufs-probe` boot argument is supplied. The probe levels are diagnostic;
levels 3–5 and 9 temporarily adopt the firmware request list and issue
read-only SCSI commands, so they require a separately approved, instrumented
temporary boot. No level is enabled in the Polaris payload command line.

The stock Polaris DTB does not carry an `iommus` property for `ufshc`. The
source retains the SDM845 apps-SMMU stream `0x100` used by the local judyln
bring-up only as an opt-in diagnostic assumption; it is not a validated
Polaris fact and is never enabled by the default payload.

This is a storage bring-up component, not a root filesystem implementation.
It does not mount APFS/HFS+, provide iOS userland, or make a flashable iOS 17
image. The port remains unqualified until it is compiled against the exact
Darwin 23 XNU records and exercised on a disposable temporary boot.

Source provenance: the local `UniXNU-judyln` SDM845 port, with the same
`GccUfs.h`, `NativeUfs.cpp`, and helper headers. No Apple or Qualcomm binary
firmware is copied into this directory.
