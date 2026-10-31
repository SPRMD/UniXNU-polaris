# A630 backend: what the local A642L reference cannot give us

Status: analysis only. Nothing here is implemented, and no GPU hardware has
been touched. This document exists so that a future backend does not start by
copying `references/unixnu-adreno6xx` and discovering these blocks later.

## The reference is gated on SM7325 values

`NativeAdrenoService.cpp` refuses to proceed unless the board fills its
`NativeAdrenoA6xxResources` with values that are specific to the Samsung
SM-T733 (SM7325 / Adreno 642L):

| Field | A642L requires | Polaris A630 declares |
| --- | --- | --- |
| `chipId` | `0x06030500` | `0x06030001` |
| `gmemBytes` | `0x80000` (512 KiB) | not in the stock DT |
| `frequencyHz` | `315000000` | not in the stock DT |
| `gpuSid` / `gpuSidMask` | `0` / `0x400` | `0` / not in the stock DT |
| `gmuSid` / `gmuSidMask` | `5` / `0x400` | not in the stock DT |
| `lpacSid` / `lpacSidMask` | `1` / `0x400` | not in the stock DT |

The mismatch is checked with `kIOReturnBadArgument` before a single window is
mapped, so a Polaris board cannot silently reuse the SM7325 procedures even if
it wanted to. That is the right behaviour and it must be preserved: the gate
belongs to the component, not to the board.

## What Polaris does declare, and what is missing

Known from the stock Polaris DT (see `polaris-a630-resources.json` and
`drivers/PolarisA630Probe/PolarisA630Board.h`):

- GPU, GMU (+PDC), GPU SMMU, GPUCC, GCC, PDC and RSCC windows.
- GPU / HFI / GMU / SMMU global and context-bank interrupts.
- Stream IDs 0 (gfx3d_user), 1 and 2 (gfx3d_secure) on the GPU's own SMMU.

## What the stock DT does answer

These were listed as unknown in the first draft of this document. All of them
turned out to be present in the appended-DTB tail, so they are read from the
tree rather than guessed:

| Field | Value | Where |
| --- | --- | --- |
| `highest-bank-bit` | 15 | `qcom,highest-bank-bit` on `kgsl-3d0` |
| GPU OPP table | 710 / 675 / 596 / 520 / 414 / 342 / 257 MHz, level 7 = 0 | `qcom,gpu-pwrlevels/qcom,gpu-pwrlevel@0..7` |
| GMU OPP table | 0 / 200 / 500 MHz | `qcom,gmu-pwrlevels/qcom,gmu-pwrlevel@0..2` |
| GMU stream IDs | `gmu_user` = 4, `gmu_kernel` = 5 | `iommus` under `/soc/qcom,gmu` |
| GPU stream IDs | `gfx3d_user` = 0, `gfx3d_secure` = <2, 1> | `iommus` under `/soc/qcom,kgsl-iommu` |
| `min-access-length` | 32 | `qcom,min-access-length` |
| UBWC mode | 2 | `qcom,ubwc-mode` |
| Snapshot buffer | 1 MiB | `qcom,snapshot-size` |
| Quirks | `gpu-quirk-hfi-use-reg`, `gpu-quirk-secvid-set-once`, `no-nap` | empty properties on `kgsl-3d0` |

Two details are worth keeping in view because they look like typos and are not:

- `gfx3d_secure` lists SID **2 before 1**. That is the DT order
  (`iommus = <&kgsl_smmu 2>, <&kgsl_smmu 1>`), so a reader that sorts or
  deduplicates the tuple silently changes which bank is which.
- The A642L gate wants `gpuSid 0`, `gmuSid 5`, `lpacSid 1`. Polaris matches on
  the first two exactly. SID 1 exists here as the second `gfx3d_secure` bank,
  not as a separate LPAC context, so the third gate value would be satisfied by
  a coincidence of numbering rather than by the same hardware meaning. Treat
  `lpacSid` as still unresolved: it must not be filled with 1 on the grounds
  that 1 happens to appear in the tree.

## What is still missing

- **A630 firmware loadability.** the images are present and hashed (see "A630
  firmware: present locally, hashed, still not loadable" below), but no PAS/SSP
  path, no signature verification and no proof of where they land - unresolved.
- **Command database layout.** see the section below - unresolved.
- **ASID assignment.** not derivable from the tree - see "ASID and context
  banks" below. The short answer is that SMMU-v2 has no ASID routing field at
  all, so there is nothing here to look up.

## ASID and context banks

The reference's third gate ("three distinct non-zero ASIDs") is the one input
that looks like a device-tree fact and is not. This section separates what the
tree proves from what the port merely assumes, and answers the question
directly: **SMMU-v2 selects a context bank by a bank index, not by an ASID, and
no ASID field exists in any of the routing registers.** The reference uses the
word loosely for a per-context software label.

### What the stock DT determines

| Fact | Value | Where |
| --- | --- | --- |
| Context-bank fault interrupts | 8, SPI 364..371 (INTID 396..403) | `interrupts` on `/soc/arm,smmu-kgsl@5040000` |
| Global fault interrupts | SPI 229 and 231 | same node |
| CB children | `gfx3d_user` (SID 0), `gfx3d_secure` (SIDs 2 then 1), `gmu_user` (4), `gmu_kernel` (5) | `iommus` tuples under `/soc/qcom,kgsl-iommu` and `/soc/qcom,gmu` |

Those values are re-derived here rather than quoted. The appended-DTB tail
(`stock-boot-unpacked/polaris-dtb-tail.bin`, 30,355,119 bytes) contains 65 FDTs
whose `totalsize` values sum to the file length exactly, and all 65 parse
cleanly under a throwaway reader. 64 of the 65 declare the GPU SMMU node (the
last does not), and in all 64 the node is byte-identical. The node's
`interrupts` is ten 3-cell entries:
`<229 4 0>, <231 4 0>, <364 4 0> ... <371 4 0>`, and `#global-interrupts = 2`
is the tree's own statement that the first two are the global pair and the
remaining eight are the context lines. That is the whole of the interrupt
evidence, and it is exact.

What is absent is as important. Across all 1,010,273 properties in those 65
FDTs, **not one property in the GPU SMMU subtree**
(`/soc/arm,smmu-kgsl@5040000`, `/soc/qcom,kgsl-iommu` and its children) has a
name containing `asid`. The complete property set there is
`status, compatible, reg, #iommu-cells, qcom,dynamic, qcom,use-3-lvl-tables,
qcom,disable-atos, #global-interrupts, qcom,regulator-names, vdd-supply,
interrupts, clock-names, clocks, attach-impl-defs, phandle, label, iommus,
qcom,gpu-offset, qcom,protect, qcom,micro-mmu-control, qcom,secure_align_mask,
qcom,retention, qcom,hyp_secure_alloc` — no `asid`, no bank index, no
`reg` on any CB child. The single `asid`-named property in the entire blob is
`qcom,no-asid-retention` on `/soc/apps-smmu@0x15000000`, the *apps* SMMU, and
it is a retention flag, not an identity.

The negative is sharper still because the same blob shows Qualcomm marking
secure banks elsewhere when it wants to: `qcom,secure-context-bank` is a
boolean on `msm_fastrpc_compute_cb9/cb10`, `qcom_cedev_s_cb` and three
`qcom,vidc` banks. None of the four GPU CB nodes carries it. So the encoder of
this device tree had a way to describe a secure context bank and did not use it
on the GPU — the GPU CB nodes are SID carriers and nothing more.

Eight fault interrupt lines are a *fault-reporting fan-out*, not a statement
that eight banks are implemented; the implemented count is `IDR1[7:0]` and can
only be read live. The DT fixes the stream IDs and the interrupt mapping, and
nothing else about contexts. `qcom,gpu-offset = <0x48000>` on
`gfx3d_user` is the one remaining number near the CB nodes; it is far larger
than any bank index and its meaning is not documented in the tree, so it is
recorded as unexplained rather than read as a bank number.

### What the tree proves about the register layout

Three independent in-tree readers agree on the same offsets, which is why this
is evidence rather than recall:

- `drivers/ShengUfs/SmmuTakeover.h` (the UFS apps-SMMU bypass path this repo
  actually ships): `0x800 + 4*slot` written as `0x80000000U | stream`,
  `0xc00 + 4*slot` written as the bank number, `0x1000 + 4*bank` written
  `0x10000`, `0x1800 + 4*bank` written `1`, and the bank's own block at
  `(pages + bank) * 4096` with `pages = 1 << (((IDR1 >> 28) & 7) + 1)`.
- `.cache/reference/UniXNU-sheng/package/SmmuBypass.h`: the same layout read
  back as `(s2cr >> 16) & 3` (TYPE) and `s2cr & 255` (CBNDX), `IDR1 & 255`
  banks, `IDR1[31]` selecting 16 KiB pages.
- `.cache/reference/unixnu-adreno6xx/NativeAdrenoGmuContext.cpp`
  (`readContext`/`contextOffset`): CBAR at `page + 4*bank`, CBA2R at
  `page + 0x800 + 4*bank`, and the per-bank block as SCTLR `+0x00`, ACTLR
  `+0x04`, TCR2 `+0x10`, TTBR0 `+0x20` (64-bit), TTBR1 `+0x28`
  (64-bit), TCR `+0x30`, MAIR0 `+0x38`, MAIR1 `+0x3c`, FSR `+0x58`.

| Register | Offset | Field that matters |
| --- | --- | --- |
| SMR n | `0x0800 + 4n` | bit 31 VALID, SID in bits 15:0 |
| S2CR n | `0x0c00 + 4n` | TYPE bits 17:16 (0 = translate), CBNDX bits 7:0 |
| CBAR n | `0x1000 + 4n` | translation-table base + type |
| CBA2R n | `0x1800 + 4n` | bit 0 = VA64 address-size extension |
| CB n block | `(pages + n) * page` | SCTLR bit 0 = enable, TTBR0/TTBR1 = the tables |

The routing arrays and the per-bank blocks are at different addresses, which is
the point: `SMR`/`S2CR` describe *streams*, `CBAR`/`CBA2R` describe *banks*,
and the bank's own `SCTLR`/`TTBR`/`TCR`/`MAIR` live in a block whose start is
`pages * page`. `pages` comes from `IDR1[30:28]` and is a live read; this
document does not assume its value. Where the arrays end and the bank region
begins therefore depends on that geometry, and the record keeps the offsets
without claiming the resulting map.

### How a context bank is actually selected

1. `SMR[slot]` with VALID=1 and `ID == SID` matches the stream.
2. `S2CR[slot].TYPE == 0` (translate) forwards that slot to a bank.
3. `S2CR[slot].CBNDX` (bits 7:0) **names the bank by index** — 0..63 in
   `NativeAdrenoSmmuContext::prepare` (`bank > 63` is rejected), `& 255` in
   the bypass path.
4. `CBAR[bank]` gives the table base and translation type, `CBA2R[bank]` the
   address width, `CB[bank].SCTLR` bit 0 enables it.

The routing identity of a stream is therefore
`SID -> SMR slot -> S2CR -> CBNDX`, and **no ASID appears anywhere in that
path**. Two streams that must not share a translation are separated by landing
in different banks, not by carrying different ASIDs.

### Where ASID does exist, and what is unproven here

ASID is real, but it lives inside the stage-1 format and in TLB maintenance, not
in the routing registers. The tree shows it in exactly three places:
`NativeAdrenoSmmuContext::prepare(..., unsigned asid, ...)` (bounded to
`<= 0xffff`), `ArmSmmu4KSyncContextTlb(io, context_offset, config_.asid, 1,
...)`, and the prose in `NativeAdrenoVm.h` ("Unmap already synchronizes by
ASID; TLBIALL for the context bank ... drops every cached translation of the
bank whatever its ASID").

**Unproven:** that the kit writes the ASID into `TTBR0[63:48]`. The kit
sources (`kits/ArmSmmu4K`) are not present in this checkout — the directory
holds only `.gitkeep` — so the bit position is a live-source question, not a
tree fact. It is recorded as unknown rather than asserted.

### Verdict on the A642L requirement

- It is **not** a device-tree value and **not** an SMMU-v2 routing field. It is
  a software pre-map sanity gate at the top of `A642LState::mapWindows()`
  (`NativeAdrenoService.cpp:376-387`): `!gpuAsid || !gmuAsid || !lpacAsid`,
  any value `> 0xffff`, or any two equal returns `kIOReturnBadArgument`. The
  same gate pins `gpuSid==0`, `gmuSid==5`, `lpacSid==1` and all three
  `*SidMask==0x400`.
- Satisfying it therefore needs a *choice*, not a lookup: any three distinct
  non-zero values that fit the ASID width would pass the gate. What the DT
  contributes is only that Polaris has four distinct SID groups to route
  (0, {2,1}, 4, 5), so "one ASID per context bank" is expressible. Which bank
  each SID lands in is decided at runtime, never by the DT: the allocator reads
  `id0 & 255` (stream groups), `id1 & 255` (banks) and
  `firstStage1 = (id1 >> 16) & 255`, marks `freeBanks[b] = !(SCTLR & 1) &&
  !referencedBanks[b]`, tries the requested bank first and then scans upward
  from `firstStage1` (`NativeAdrenoService.cpp:415-555`). Only the *bank* is
  resolved there; the ASID is passed through unchanged to
  `bringUp(io, bank, asid, ...)`.
- The third ASID has no Polaris counterpart at all: the stock DT declares no
  LPAC node and no LPAC SID. `lpacSid` is **still unresolved** and must not be
  filled with 1 on the strength of SID 1 appearing as the second
  `gfx3d_secure` bank.
- So the honest statement is the one this document was asked to test: for
  routing, SMMU-v2 has no ASID field and the reference uses the term loosely;
  for translation and TLB maintenance ASID is architectural, but its value is a
  port policy input, not something any node in the tree can supply.

### Still unknown offline

- `IDR0`/`IDR1`/`IDR2` for the GPU SMMU (SMR group count, implemented bank
  count, page size, address widths) — live read only.
- Whether the GPU SMMU exposes CBA2R at all; every in-tree reader uses
  `0x1800`, so the tree is consistent but does not prove the block is present
  on this instance.
- Which bank numbers are free at handoff.
- The ASID field position the kit uses in `TTBR0`.
- Whether the reference's `firstStage1` filter is even meaningful on this
  SMMU: `IDR1[23:16]` is the first stage-1-implementing bank, and no local
  artefact records it for the GPU instance.

One wording problem is flagged rather than fixed, because
`drivers/PolarisA630Probe/**` is outside this task's scope:
`PolarisA630Board.h` comments the context interrupts as "Ten hardware
context-bank interrupts, in DT order 364..371 plus the pair". The "ten" is the
eight context lines plus the two global lines, which are not context-bank
interrupts. The macros themselves are right —
`POLARIS_A630_SMMU_CONTEXT_IRQ_FIRST_SPI` is 364 and
`POLARIS_A630_SMMU_CONTEXT_IRQ_COUNT` is 8 — so only the prose is wrong.

## GMEM geometry: resolved from a local driver, not from hardware

The first draft said GMEM size was unknowable offline. It is knowable, and the
answer was already in this workspace.

`polaris_ios16_driver_research/hackios-xnu-kernel/xnu/files/bsd/dev/hakios.adreno.c`
drives an A630/A640-generation Adreno from Darwin. Its `a640` branch - which is
the branch that loads `a630_sqe.fw` and `a640_zap.mdt`, so "a640" there means
the A630/A640 generation and not SM8150 - does two things worth copying:

| Fact | Value | Where in that file |
| --- | --- | --- |
| GMEM base | `0x00100000` | `uche_gmem_range_min` = `GPU_WORD(0x0e0b)` set to `0x100000` |
| GMEM end | `0x001fffff` | `uche_gmem_range_max` = `GPU_WORD(0x0e0d)` set to `0x1fffff` |
| GMEM size | 1 MiB | the `GMEM_SIZE` query returns `1024*1024` for a640, `512*1024` otherwise |
| GMEM_BASE invariant | must equal `UCHE_GMEM_RANGE_MIN` | a comment on the `0x06` query case says exactly that |

So the range is `[0x100000, 0x1fffff]`, i.e. 1 MiB starting at 1 MiB, and the
register pair is `0x0e0b`/`0x0e0d` in the UCHE block. This is a *driver*
constant, not a device-tree claim: it is what a working Darwin driver programs.
It still is not a live read of polaris silicon, so `gmem_bytes` is recorded as a
value to program, not as a confirmed property of this specific unit.

Note the disagreement worth knowing about: mainline Linux computes the range the
same way (`a6xx_gpu.c`, `gmem_range_min + info->gmem - 1`) but takes `info->gmem`
from a per-chip table, and for A630 that table's entry is 512 KiB, not 1 MiB.
The two sources disagree by a factor of two. Until one is checked against real
hardware, the 1 MiB figure must be treated as "what the local Darwin driver
does", and the discrepancy is the first thing a live read should settle.

## A630 firmware: present locally, hashed, still not loadable

The first draft said no A630 image had been located, and a later draft said the
reference "loads A660 firmware" as if an A660 image were sitting next to the
A630 one. Both are wrong in the same direction, so both are corrected here.

**No A660 firmware image exists anywhere on this host.** A filename scan for
`a660`/`a6xx`/`a640` over the whole workspace returns zero firmware files; the
only A660 material is reference *source* —
`references/unixnu-adreno6xx/NativeAdrenoA6xxGmu.cpp`, whose header comment
reads "A660 firmware, RSCC and HFI procedures follow Qualcomm's A6xx GPU
driver". That is a procedure written against A660, not an A660 blob. The
firmware actually present is A630-named and comes from the stock MIUI
V12.5.1.0.QDGCNXM package.

Every A630-named artefact reachable offline is now recorded in
`research/polaris-a630-resources.json` under
`firmware_regions.a630_firmware_inventory` — 38 files, each with its exact
path, byte count and SHA-256. They collapse to eight distinct payloads:

| File | Bytes | SHA-256 (first 16) | What it is |
| --- | ---: | --- | --- |
| `a630_gmu.bin` | 32,768 | `b07f90299ff2ae33` | GMU firmware; payload ends at offset 18,020, rest is zero padding |
| `a630_gmu.bin` (variant) | 20,480 | `894ae5550352d2d1` | strict prefix of the 32,768-byte image — no extra payload |
| `a630_sqe.fw` | 31,980 | `34edacb6fdedfbfc` | CP microcode (first word is not microcode — `hakios.adreno.c` copies from offset 4) |
| `a630_zap.mdt` | 6,684 | `1882b214d24c13ea` | ZAP shader, ELF32 header: 3 program headers, no section table |
| `a630_zap.b00` | 148 | `b2975f6a4c28a981` | ZAP segment 0 |
| `a630_zap.b01` | 6,536 | `c94da0d6edf48208` | ZAP segment 1 |
| `a630_zap.b02` | 1,968 | `519b5538809f54ee` | ZAP segment 2 |
| `a630_zap.elf` | 14,256 | `c0a830808c7ae886` | pre-linked ZAP ELF; **not** the `mdt+b00+b01+b02` concatenation (15,336), so its provenance is unproven |

The 38 paths are 35 byte-identical copies of the MIUI files spread over six
locations — `polaris_ios16_driver_research/.local/miui-a630`, the
flashable-driver tree, three `out/` bundles and
`proprietary/sdm845-a630-firmware` — plus two copies of the derived
`a630_zap.elf` and the 20,480-byte GMU variant. Every repeated file carries
`duplicate_of` naming the MIUI original, so 38 is a distribution fact, not 38
independent images.

So the ZAP shader and the GMU firmware are **present**. What is missing is
everything that would make them usable, and it is not a matter of finding more
bytes:

- No PAS/SPSS authentication path for the GPU exists in this tree, so nothing
  can hand these images to the secure world.
- No signature or TrustZone verification has been performed on any of them.
- The 32,768-byte GMU image is only *plausibly* within the `0x8000`-byte flat
  ITCM bound that the local Linux `a6xx_gmu.c` describes for A630-family
  legacy loading. Its 16-byte block header (`0x43f80`, length 9) does not
  parse as the reference's own block chain, so the reference's loader cannot be
  pointed at it without a format answer that no local artefact supplies.
- Nothing shows that either reserved window — `gpu_region` (`0x8c415000`,
  8 KiB) or `pil_spss_region` (`0x97f00000`, 1 MiB) — is where any of these
  images is meant to land.

Every entry therefore carries `usable_for_polaris: false`, and the reason
field says why per kind of file. Owning the bytes is not loading them: the
inventory is a provenance record, not a capability.

## Command database

The stock DT does not give the command database. It gives a *locator*:

```
/soc/qcom,cmd-db@861e0000
    compatible = "qcom,cmd-db";
    reg        = <0xc3f000c 0x8>;
```

Parsed from the authoritative appended-DTB tail (`polaris-dtb.bin`, the P2 v2.1
entry recorded in `polaris-a630-resources.json`): node `qcom,cmd-db@861e0000`
under `/soc`, `compatible = "qcom,cmd-db"`, `reg = <0xc3f000c 0x8>`. The string
`0x861e0000` does not occur in that blob at all; `861e0000` is only the
unit-address in the node *name*, and the address the DT actually maps is
`0xc3f000c`. That is the whole of what the board tells us.

### How `0xc3f000c` resolves

The 8 bytes are two little-endian `u32`s, not the database:

| Locator offset | Meaning |
| --- | --- |
| `+0x0` | physical address of the command database |
| `+0x4` | size of the command database in bytes |

This reading is not inferred from memory. It is the decode performed by the
in-tree source `polaris_ios16_driver_research/.local/sweet_rpmh.c`, which maps
exactly 8 bytes at `0x0c3f000c` and then reads `+0` as the address and `+4` as
the size before mapping the real database (`rh_map()`, the `rh_dict` block).
That file is a hand-written driver for a *different* board (SWEET / PM6150L),
so it corroborates the shape of the indirection without proving that SDM845
stores the same pair there. Treat the decode as the tree's working model, not
as a verified SDM845 fact.

### Structure, as far as the tree justifies it

The same source carries a full parser, so the layout below is read from code
rather than recalled. Header is 144 bytes (`RH_DB_HEADER`); entries are 24
bytes (`RH_DB_ENTRY`); magic `0x0c0330db` (`RH_DB_MAGIC`) is checked at header
offset 4, with version at 0, checksum at 136 and flags at 140:

| Header region | Contents |
| --- | --- |
| `+0x00` | version (the parser accepts only 1) |
| `+0x04` | magic `0x0c0330db` |
| `+0x08 + 16*i` | slave descriptor `i`, at most 8 |
| `+0x88` | checksum |
| `+0x8c` | flags (bit 0 set means standalone, which is refused) |
| `+0x90` | first entry / auxiliary region base |

Each 16-byte slave descriptor is `{slave_id:u16, entries_off:u16, aux_off:u16,
count:u16, aux_version:u16, pad}`, where both offsets are relative to the
144-byte header. Each 24-byte entry is:

| Entry offset | Field |
| --- | --- |
| `+0x00` | resource id, 8 bytes (the 8-character name packed little-endian) |
| `+0x08` | priority pair |
| `+0x10` | address `u32` |
| `+0x14` | auxiliary length `u16` |
| `+0x16` | auxiliary offset `u16` |

Entries are looked up by that 8-character id, not by a numeric index. This is
the `{id, ..., offset, len}` shape the public layout describes, with the
priority pair and the auxiliary pair filling the middle of the 24 bytes.

### The ARC index mapping is *not* what the reference does

The premise for this work was that the A642L reference reads ARC indexes out of
the command database by id. It does not.
`references/unixnu-adreno6xx/NativeAdrenoA6xxPower.cpp`, `arcVote()`, builds the
vote purely from the *auxiliary* payload attached to each resource entry:

```
*vote = voltage << 16 | secondaryIndex << 8 | primaryIndex;
```

where `primaryIndex` and `secondaryIndex` are searched out of the per-resource
`u16` auxiliary tables, and `bcmVote()` likewise divides by
`little16(resource.auxiliary + 4)` and `little32(resource.auxiliary)`. The
indexes are therefore *derived at runtime from the auxiliary blob of the
looked-up resource*, not stored as a global ARC table addressed by id. That
changes what a port has to fetch: it needs the auxiliary payload for the
specific GPU and GMU resources, which is a property of the database contents,
not of the layout.

### The two local DT sources disagree, and that is recorded, not resolved

Scanning every DTB in the tree (107 files, 50 with a `cmd-db` node) finds two
incompatible encodings of the same binding:

| Form | Count | `reg` | Example |
| --- | --- | --- | --- |
| locator | 46 | `<0xc3f000c 0x8>` | the stock Polaris appended tail |
| reserved-memory | 4 | `<0x0 0x85fe0000 0x0 0x20000>` | `sdm845-xiaomi-polaris.dtb` |

The in-repo `.cache/reference/edk2-msm-full` copy of `sdm845-xiaomi-polaris.dtb`
uses the *second* form: a `reserved-memory/aop-cmd-db-mem@85fe0000` node with
`compatible = "qcom,cmd-db"` and a 128 KiB reserved region. The authoritative
device tail uses the *first* form and does not contain `0x85fe0000` at all.
These are different device trees describing the database differently, and
nothing local says which one the shipping firmware boots. Both are recorded;
neither is promoted to the answer. All four reserved-memory DTBs are sdm845
(`zs600kl`, `generic-msd`, `axolotl`, `xiaomi-polaris`), so the split is not a
polaris-versus-everyone artefact.

### What is still missing, and exactly what would close it

Not derivable from any local byte:

- the address and size stored at `0xc3f000c`, and therefore the database itself;
- which of the two DT encodings the boot firmware actually honours;
- whether SDM845 uses the same 144/24 layout as the SWEET parser above.

No command database image is present locally. A byte scan of all 27,099 files in
the repository for the little-endian magic `0x0c0330db` returns zero hits, and
the same scan over the wider research tree also returns zero. The
`CmdDbDxe.efi` that *is* in `references/` is the DXE driver that performs this
lookup at runtime, not a copy of the data, and it is built for a different part
(`KodiakLAA`, sm8350) - it contains no magic and cannot supply the values.

Closing this needs one of:

1. a dump of the 8 bytes at physical `0xc3f000c` plus the region they point at,
   i.e. a live read on the device, which is out of scope here; or
2. the vendor `cmd-db` blob from the Polaris firmware package, if the package
   ships one pre-built rather than generating it at boot.

Until then the state is unchanged: the locator is understood, the database is
not.

## Consequence

Reusing the reference still means porting its *procedures* (register sequences,
HFI handshake, SMMU context-bank setup) onto SDM845, but the address, interrupt
and stream-ID inputs are now read from the tree instead of being guessed, which
removes the largest class of silent errors. What is left is genuinely
hardware-shaped: GMEM geometry, the A630 firmware set, the command-database
indirection and the ASID policy cannot be derived from any node, and the
reference's own gate keeps rejecting polaris until they are supplied. Of these,
the ASID policy is the one that is now *answered negatively* rather than left
open: see "ASID and context banks", which shows there is no ASID field to read
and that the gate wants three chosen values, not three discovered ones.

Until then the honest state is `resource-contract`: complete window/SID record,
zero hardware action. `polaris-a630-darwin-driver-ready` stays false.
