# UniXNU on Xiaomi Mi MIX 2S (polaris)

Device port for SDM845 / Snapdragon 845 / Adreno 630 on UniXNU's Darwin 23
architecture (XNU 10063, source-kernel platform milestone). The retired
ABL-shim chain ([ios16_on_polaris_mix2s](https://github.com/luuu20309/ios16_on_polaris_mix2s),
XNU 8796 / iOS 16) is the measured-hardware reference for this tree.

**The platform stage is verified on real hardware** (user-approved temporary
`fastboot boot` sessions, 2026-10-24). The full chain — Renegade edk2-msm
firmware → UniXNU boot manager from an ESP on userdata → DarwinBoot hand-off
(upper-bank window, real 1080×2160 GOP) → XNU entry → scheduler, timer
interrupts, corecrypto FIPS POST, BSD init, IOKit — runs to the designed
platform boundary, where it panics `Failed to mount root device` because this
kernel has no root by design. There is no userland, no touch/display/GPU
driver and no daily-usable system on this tree yet.

## English

### What "transfer from ABL" means here

The old chain booted XNU 8796 through Android's ABL: a boot image with a
custom shim that inherited ABL's framebuffer and UFS state, a forged iPhone X
(D22AP) identity in the ADT, and 93 patches against the SWEET machine
configuration. That chain reached the iOS 16 lock screen with touch — evidence
that belongs to that tree only.

This repository moves the port onto UniXNU's build driver and boot chain:

| Aspect | Old ABL-shim chain | This repository |
| --- | --- | --- |
| Kernel | XNU 8796, MACHINE_CONFIG SWEET, darwin-xnu-build | XNU 10063, BCM2837 4 KiB pages, `unixnu` build driver |
| Build | macOS CI wrapping blacktop/darwin-xnu-build | `scripts/build-platform-kernel.py` on UniXNU `37987aea` |
| Boot | boot.img → custom shim → kernel | edk2-msm (Renegade) firmware → UniXNU → DarwinBoot → payload kernel.macho |
| ADT | iPhone X identity, ABL framebuffer/UFS nodes | platform ADT, `darwinboot-memory-range`, no Apple identity |
| Root | iOS 16 userland on UFS/HFS+ | none yet (platform stage, by design) |
| CPU | cpus=4 proven (A55 0-3); A75 4-7 never observed | same topology; prefix check migrated; scheduler proven on hardware |

### Implemented and verified

- **Host**: polaris platform ADT generator, binary-ABI tests, fail-closed CPU
  prefix check (migrated from the old chain), sanitized MIUI fact extraction,
  and a stock-DTB resource contract probe. CI green for the Python/ADT gates. The `drivers/PolarisTouch` and `drivers/PolarisProtocols` directories are host-side protocol references; `PolarisSynapticsTouch`, `PolarisTransportContracts` and `PolarisA630Probe` are board-gated Darwin contract-only services and do not claim hardware I/O or readiness.
- **Local driver inputs**: `scripts/make-polaris-driver-bundle.py` hashes every
  checked-in Polaris source component and can record matching firmware from a
  user-supplied MIUI/WOA tree. The default is metadata-only; `--copy-vendor` is
  an explicit local-only choice and still leaves the bundle non-flashable.
- **Storage bring-up**: the SDM845 `ShengUfs` read-only probe from the local
  Polaris/UniXNU-judyln port is now present and linked behind
  `CONFIG_XNU_NATIVE_UFS`. It is default-off at runtime and remains
  unqualified until the exact Darwin 23 compiler record and a disposable
  temporary boot validate it.
- **EFI/QEMU**: UniXNU EFI apps and the DarwinBoot override build and pass ten
  QEMU cases (menu, hand-off, ARM64 entry with Darwin 23 boot_args, allocation
  window, refusals). CI green.
- **Source kernel**: builds on the macOS runner; the QEMU native check proves
  CPU registration and advancing timer IRQs on every build. CI green.
- **Real hardware** (photographed evidence, user-approved temporary boots):
  Renegade edk2-msm polaris firmware boots; UniXNU menu runs from the ESP
  flashed to userdata; DarwinBoot validates and hands off
  (`va=0xfffffff007004000 pa=0x100004000`, `video base=0x9d400000 1080×2160`);
  the XNU kernel executes through arm_init, the scheduler, the STARTUP chain,
  the corecrypto FIPS POST, bsd_init and IOKit, and stops at the designed
  root-mount boundary. bsd_init cannot run without working timer interrupts,
  so the real-phone GIC/PPI-19 timer path is established by execution.
- **Diagnostic tooling built during bring-up**: entry-probe stage bars and
  on-screen panic for the phone (caves relocated into verified zero windows),
  on-demand kernel disassembly in CI, payload ESP assembly with automatic
  FIPS-HMAC re-sealing.

### Two UniXNU-wide bugs found and fixed here

1. **The BCM2837 fixed panic-log address (0x3c0fc000) bus-errors on SDM845**:
   every non-Raspberry-Pi hardware port silently dies in `PE_create_console`
   while QEMU tolerates the read. Fix: `CONFIG_XNU_DT_PANIC_REGION=y` (the
   device-tree probe from UniXNU's own patch).
2. **Post-link kernel patching invalidates the FIPS POST integrity HMAC**:
   any tool that rewrites `__text` after the base build's seal must re-run
   `seal-source-crypto-kernel.py`; `make-payload-esp.py` does this now.

### Boot-image recipe (Route A)

`fastboot flash userdata esp.img` (a 128 MiB FAT32 ESP with the boot manager,
DarwinBoot, the kernel and the polaris ADT) plus `fastboot boot
boot-polaris.img` (Renegade firmware, built from
[the edk2-msm fork](https://github.com/luuu20309/edk2-msm)). All writes were
user-approved; boot/modem/persist partitions untouched. Details in
[NOTES.md](NOTES.md); firmware background in
[research/uefi-firmware-plan.md](research/uefi-firmware-plan.md).

### Guarded package output

CI also runs `scripts/make-polaris-package.py`. It bundles the ESP tree,
kernel report, firmware provenance, driver contract and SHA-256 manifest into
`polaris-one-click/`, and emits `flash.cmd`/`flash.ps1`. The installer checks
the manifest, the connected product and the single-device rule before any
write. The current contract deliberately produces `flashable=false`: no
prelinked userland kernel, qualified userdata root, complete Darwin hardware
drivers or independent temporary-boot report exists yet. This is a build
artifact and evidence package, not a claim that the phone can run iOS.

The optional `polaris_ipados17_defconfig` workflow path now assembles an
experimental iPadOS 17 stage from locally or remotely fetched IPSW members.
`scripts/build-ios-stage.py` creates the trust bundle, iOS ESP and separate
`darwin-root.img`, and the guarded package can carry that root image. The
stage is still evidence-only: the SDM845 UFS root handoff, Apple userland and
all peripheral backends require a real temporary-boot report before the
installer can ever be enabled.

### Repository layout

Standard UniXNU device repository: `board.toml`, `configs/polaris_defconfig`,
`drivers/ArmCpu` (timer PPI from the ADT + the heartbeat probe),
`drivers/DarwinBoot` (upper-bank allocation window), `drivers/PolarisBoardProbe`
 (opt-in read-only DT resource inventory), `drivers/PolarisHardwareServices`
 (opt-in read-only keys/display/touch/power/wireless/camera resource inventory),
`drivers/PolarisSynapticsTouch` and `drivers/PolarisTransportContracts`
 (board-gated Darwin contract-only services), `drivers/PolarisTouch` and
`drivers/PolarisProtocols` (host-side bounded protocol references),
`drivers/PolarisGeniI2c` (host-testable GENI FIFO state machine),
`drivers/PolarisA630Probe` (board-gated, read-only Adreno 630/GMU/SMMU
resource contract),
`drivers/ShengUfs` (SDM845 read-only UFS probe, default-off), `scripts/` (ADT,
resource probe, ESP assembly, platform kernel build, probes), `tests/`, CI
workflows for host/EFI, kernel+QEMU and ESP images. Pinned upstream revisions
are in [upstream.json](upstream.json).

The transport contract service supplies bounded Darwin-buildable protocol cores
for WCN399x H4/WLFW, PN54x NCI, and camera CCI. It remains disabled by default
and does not claim Wi-Fi, Bluetooth, NFC, or camera functionality until a real
Polaris transport and temporary-boot test exist.

### Next stages

A root for the kernel (ramdisk/mockfs first, UFS later), then the prelink and
Apple-identity decision, then a Darwin 23 touch/display driver. The current
touch work stops at a host-side RMI4/PDT/F12 reference and leaves touch disabled
until compilation and a temporary Polaris boot provide evidence. The full
history of both chains is in [docs/HISTORY.md](docs/HISTORY.md).

## 简体中文

### 现状

**平台阶段已在真机验证**(2026-10-24,经用户批准的 `fastboot boot` 临时
引导):Renegade edk2-msm 固件 → userdata ESP 上的 UniXNU 菜单 →
DarwinBoot 交接(上 bank 内存窗、真板 1080×2160 GOP)→ XNU 入口 → 调度
器、timer 中断、corecrypto FIPS 自检、BSD init、IOKit——一路跑到平台阶
段的设计边界(无根内核按设计 panic 在 root mount)。内核在此树上无用户
态、无触摸/显示/GPU,不是日用系统。

### 本次移植期间发现并修复的两个通用 bug

1. UniXNU 的 BCM2837 机器配置把树莓派 SoC 的固定 panic-log 地址
   (0x3c0fc000)编进内核,`PE_create_console` 无条件访问;QEMU 宽容而
   **任何非树莓派真机都会静默死**。修复:启用设备树 panic-region 探测。
2. 内核链接后修改 `__text`(探针等)会使 FIPS POST 完整性 HMAC 失配;
   ESP 组装流程现在在修改后自动重新封印。

### 构建与复现

```sh
# 本地检查(仅 Python)
python3 -m unittest discover -s tests -v

# CI:内核 + QEMU native check + ESP 镜像(esp-image / disasm 按需)
# 真机:esp.img 刷 userdata + fastboot boot 固件,详见 NOTES.md
```

### 来源

板级测量与历史:[ios16_on_polaris_mix2s](https://github.com/luuu20309/ios16_on_polaris_mix2s) ·
完整迭代史:[docs/HISTORY.md](docs/HISTORY.md) · 移植模板:UniXNU-sweet ·
基线:[UniXNU](https://github.com/UniXNU/UniXNU) `37987aea`,BSD-2-Clause-Patent。
不包含 Apple 二进制、Qualcomm 固件、设备转储或序列号。
