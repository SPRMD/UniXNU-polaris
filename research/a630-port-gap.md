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

Not known, and not guessable from the tree:

- **GMEM size and highest-bank-bit.** The A6xx HwInit and ring setup need both.
  `qcom,highest-bank-bit` is read by the probe if present; the stock polaris
  nodes do not carry it.
- **GPU frequency table.** The A642L reference builds HFI/BCM payloads from the
  running command database for SM7325. SDM845's GPU OPP table and the matching
  ARC indexes would have to be derived from the polaris `qcom,gpu-pwrlevels`
  nodes, which the probe does not currently parse.
- **ZAP shader and the `a630_*` firmware images.** The reference loads A660
  firmware. Polaris needs the A630 set; `pil_spss_region` (`0x97f00000`,
  1 MiB) and `gpu_region` (`0x8c415000`, 8 KiB) are reserved but no image has
  been located or verified.
- **Command database layout.** `/soc/qcom,cmd-db@861e0000` resolves to a
  8-byte `reg` at `0xc3f000c`, which is a pointer, not the database itself.
  The reference reads ARC indexes from it; on polaris that indirection has not
  been resolved.
- **ASID assignment.** The reference requires three distinct non-zero ASIDs
  (gpu, gmu, lpac). Polaris has no recorded ASID policy.

## Consequence

Reusing the reference means porting its *procedures* (register sequences, HFI
handshake, SMMU context-bank setup) onto SDM845 values that do not exist in this
tree yet. That is a hardware-evidence task, not a refactor: several of the
missing values can only be confirmed by reading the live GPU under a
user-authorised temporary boot.

Until then the honest state is `resource-contract`: complete window/SID record,
zero hardware action. `polaris-a630-darwin-driver-ready` stays false.
