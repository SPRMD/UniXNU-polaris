# Polaris partition plan: where a darwin root can actually live

Status: **not executed**. Nothing in this document has been written to a phone.
`flashable` stays `false`; this is a prerequisite plan, not a flash recipe.

## The problem

The guarded package stages two images onto two different GPT partitions:

| image | intended partition | size |
| --- | --- | --- |
| `esp.img` (FAT16 ESP: boot manager, DarwinBoot, kernel, ADT, trustcache) | `userdata` | 268,435,456 B |
| `darwin-root.img` (SHNGROOT: iPadOS 17 OS + SystemOS) | `darwin` | 9,381,609,472 B |

The second row cannot happen. A read-only `fastboot getvar all` on the test
device (`72cdaeac`, `product: polaris`, `hw-revision: 20001`) enumerates 85
partitions and **none of them is named `darwin`**:

```
abl_a abl_b aop_a aop_b apdp bk01..bk53 bluetooth boot cache cdt cmnlib_a
cmnlib_b cmnlib64_a cmnlib64_b cust ddr devcfg_a devcfg_b devinfo dip dsp dtbo
frp fsc fsg hyp_a hyp_b ImageFv keymaster_a keymaster_b keystore limits logdump
logfs logo minidump misc modem modemst1 modemst2 msadp oops persist persistbak
qupfw_a qupfw_b recovery sec splash spunvm ssd sti storsec_a storsec_b switch
system toolsfv tz_a tz_b userdata vbmeta vendor xbl_a xbl_b xbl_config_a
xbl_config_b
```

`fastboot flash darwin <image>` therefore fails at the bootloader, after the
package checksum pass has already succeeded. The installer now probes
`partition-size:darwin` first and refuses with an explicit message (exit 12)
instead of surfacing an opaque bootloader error.

## The space is there; the partition is not

`userdata` alone is large enough for both images:

| fact | value |
| --- | --- |
| device `partition-size:userdata` | `0x1C457FB000` = 121,425,080,320 B (121.43 GB) |
| `board.toml` `first_lba` | `0x300000` (1,610,612,736 B) |
| `board.toml` `last_lba` | `0xE52BFD7` |
| derived size | 121,425,080,320 B |

The `board.toml` geometry matches the device exactly, so the numbers are
already trustworthy. What is missing is a second partition entry carved out of
that range.

## Options, none of them executed

1. **Repartition the phone.** Shrink `userdata` and create a `darwin` partition
   of at least 9,381,609,472 B plus slack, by rewriting the GPT. This is a
   destructive operation on the partition table and is the only option that
   makes the current package layout correct.
2. **Put SHNGROOT inside userdata.** Keep one partition and place both the ESP
   FAT and the SHNGROOT windows inside it (the `make-userdata-linux.py`
   `--partition` flag already models a GPT partition holding SHNGROOT; the
   `board.toml` `[userdata]` `windows` table already lists `OS` and
   `SystemOS`). This avoids touching the GPT but means `flash.ps1` must stop
   emitting `flash darwin` and the ESP must move off `userdata` (it cannot
   share the raw partition with SHNGROOT windows without a filesystem that
   understands both).
3. **Drop the root image from the package.** Ship the ESP-only stage: boot
   manager, DarwinBoot, kernel, ADT, trustcache, firmware. That is the shape
   the 2026-10-24 temporary-boot log already exercised on hardware, and it
   needs no partition work at all.

Option 3 is the only one that requires no destructive step, and it is the one
that matches the evidence the project actually has.

## What must be read before any of this is attempted

- The live GPT (primary and backup headers plus the full entry array) from the
  device, not the `getvar` summary. `getvar` gives sizes, not LBAs, and the
  `board.toml` first LBA came from MIUI's `rawprogram0.xml`, not from this
  phone.
- Whether `userdata` currently holds anything the user wants. The 2026-10-24
  log records an approved `fastboot flash userdata esp.img`, so the partition
  has already been overwritten once on this device.
