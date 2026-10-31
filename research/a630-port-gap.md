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

- **GMEM size.** The A6xx HwInit and ring setup need it and no polaris node
  declares it. It is a property of the part, not of the board, so it would have
  to come from a live read or from the A630 programming guide.
- **ZAP shader and the `a630_*` firmware images.** `gpu_region`
  (`0x8c415000`, 8 KiB) and `pil_spss_region` (`0x97f00000`, 1 MiB) are
  reserved, but no image has been located or verified, and the reference loads
  A660 firmware.
- **Command database layout.** `/soc/qcom,cmd-db@861e0000` resolves to an
  8-byte `reg` at `0xc3f000c`, which is a pointer, not the database. The
  reference reads ARC indexes through it; that indirection is unresolved.
- **ASID assignment.** The reference requires three distinct non-zero ASIDs.
  The DT gives stream IDs, not ASIDs, so no policy can be derived from it.

## Consequence

Reusing the reference still means porting its *procedures* (register sequences,
HFI handshake, SMMU context-bank setup) onto SDM845, but the address, interrupt
and stream-ID inputs are now read from the tree instead of being guessed, which
removes the largest class of silent errors. What is left is genuinely
hardware-shaped: GMEM geometry, the A630 firmware set, the command-database
indirection and the ASID policy cannot be derived from any node, and the
reference's own gate keeps rejecting polaris until they are supplied.

Until then the honest state is `resource-contract`: complete window/SID record,
zero hardware action. `polaris-a630-darwin-driver-ready` stays false.
