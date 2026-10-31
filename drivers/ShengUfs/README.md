# Polaris UFS: probe plus experimental read-only block backend

Default build and runtime behavior remains probe-only. No hardware qualification
or successful root mount is claimed. The existing iPadOS config comment saying
root is already connected is incorrect; config/packaging edits belong to the
integrator and are intentionally outside this change.

## Build and runtime switches

- `python3 scripts/build-arm-driver.py ShengUfs`: probe archive. No storage
  header or IOBlockStorageDevice class dependency is introduced in this mode.
- `python3 scripts/build-arm-driver.py ShengUfs --ufs-block-runtime`: additionally
  compile PolarisUfsBlock (`POLARIS_UFS_BLOCK_RUNTIME=1`), refreshing pinned
  IOStorageFamily headers. Link `build/storage-base/libIOBlockStorageDevice.a`
  built by `scripts/build-storage-base.py` into the source kernel as required.
- Only `native-ufs-block=1` enables the block runtime. It requires the existing
  root-device NativeUfs personality and rejects concurrent `native-ufs-probe`
  or `native-ufs-smmu` takeover. No board, workflow or manifest is changed here.
- `native-ufs-root=1` is NOT implemented by this backend. Keep it disabled.

The new device publishes **LUN 0 with its actual 4096-byte sector geometry**,
not a 512-byte reinterpretation of its GPT. READ CAPACITY(10) must return a
4096-byte block size and a non-sentinel last LBA. Other geometries are refused.
Reads use the existing single-slot UTRD/UPIU/PRDT path, READ(10), cache maintenance,
128 KiB chunks, serialized bounce-buffer copy, and completion outside both locks.
Writes, format and write-cache changes are rejected. Persistent-store write
helpers were removed; transport submission also rejects host-to-device data.
Timeout/fatal/protocol errors quarantine DMA and prevent subsequent submissions.

## Handoff requirements and evidence

The runtime adopts an already powered, idle firmware controller; it does not
initialize clocks, reset, QMP PHY, regulators, ICE, link training or SMMU contexts.
It reads GCC power/bus gates before accessing UFS, allocates its own contiguous
DMA buffer (never reuses firmware request pages), and checks all sixteen UFS
streams for explicit pre-existing SMMUv2 BYPASS mappings before changing the
request list. Missing, overlapping, translated, extended-ID or disabled-SMMU
mappings are refused. No runtime SMMU register is written. DMA is deliberately
restricted below 4 GiB. Qualcomm's disabled-context bypass quirk is NOT assumed.
An attempted runtime start is single-shot. DMA allocations and maps remain
pinned for the boot, including failures, because a proven abort/reset and safe
unload protocol is not implemented. This is an experimental built-in driver.

Primary/static evidence:

- Linux `arch/arm64/boot/dts/qcom/sdm845.dtsi`: UFS HC `0x01d84000/0x2500`,
  interrupt SPI 265, apps SMMU `0x15000000/0x80000`, UFS `iommus =
  <&apps_smmu 0x100 0xf>`. The local primary-source copy is in
  `polaris_ios16_driver_research/refs/WSL2-Linux-Kernel-linux-msft-wsl-6.18.y`;
  file SHA-256 `d93d27b099a5ddec7dfb7148409b747b235131647a25c697ba6569916ff86eee`.
- Linux v6.12 `drivers/iommu/arm/arm-smmu/arm-smmu.h`, checked from the
  torvalds/linux GitHub contents API: sCR0 CLIENTPD bit 0 / EXIDENABLE bit 3,
  ID0 SMS bit 27 / NUMSMRG bits 7:0, SMR VALID bit 31,
  S2CR TYPE bits 17:16 with BYPASS=1. The runtime reads only the first 4 KiB
  of the SDM845 SMMU window; it never uses the inherited SM8550 0xd0000 span.
- Block adapter derived from local `UniXNU-judyln/drivers/ShengUfs/
  NativeUfsFull.cpp.txt`, checkout HEAD
  `d6c116a0ac2f8414cb53d24318e8d9466047fa8c`, file SHA-256
  `2282ab5b86357aa5f0733d3580c66975676c05923b7ea7c8b7dc1e36c7629b6f`.
- IOStorageFamily headers/base source are pinned to Apple public revision
  `e45fbe30a7879e0b16e26dddb78538f1b00e0bff`.

These sources establish register definitions, not the safety/state of a specific
Polaris UEFI handoff. Stock Polaris DT lacks the UFS iommus property; older local
notes also mention 0x720, and inherited sheng comments mention 0x60. Neither is
used by this runtime. Still needed: instrumented confirmation of current Polaris
SIDs, nonsecure SMMU access, GCC/controller power, identity DMA routing and
exclusive queue ownership. Readback checks cannot substitute for that validation.
Legacy probe/SMMU-takeover modes retain their historical diagnostic behavior and
assumptions; their SM8550 hardware comments are not Polaris evidence.

## Root packaging gap

The package uses userdata for ESP and a separate GPT `darwin` partition containing
SHNGROOT OS/SystemOS disk windows. Publishing LUN 0 alone does not publish those
embedded disks and cannot satisfy APFS root matching. RootLayout.h remains the
old userdata diagnostic parser, and is NOT called by the new block start path.
The next stage must select and bound-check `darwin`, validate SHNGROOT and each
window against both partition and detected LUN capacity, publish the OS/SystemOS
windows with their own 512-byte logical geometry, then establish media/root
matching. TrustCache/ADT and IOStorageFamily matching/link integration are separate
requirements. No root-success property, root boot argument or packaging is added.

## Validation (2026-10-31)

- WSL clang++ C++17, `-Wall -Wextra -Werror`, ASan/UBSan:
  Run `python3 -m unittest discover -s tests -p test_ufs_runtime.py -v`.
  `tests/ufs_runtime_host.cpp` executes production transport and block code with
  mock MMIO/IOKit. Covers chunked byte-exact reads, bounds, write rejection,
  capacity rejection, stream coverage/conflicts, short copy, completion lock
  discipline, timeout/fatal/protocol quarantine and stopped-device reads.
- `python -m unittest discover -s tests -p test_storage_build.py -v` verifies
  warning forwarding pairs and malformed compile records.
- Existing `test_ufs_source.py` passes.
- Probe and block modes both pass cross-clang Darwin syntax checking against
  CI tree `/root/polaris-ci-headers-41179395488`, with the pinned storage headers.
  Commands/logs are in `out/ufs-syntax/`. The Linux TargetConditionals shim from
  UniXNU was used only for this host syntax check; native builds use the SDK.

No full native archive/kernel link, phone I/O, publication, root mount or iOS boot
has been validated. No phone access, commit or push was performed.
