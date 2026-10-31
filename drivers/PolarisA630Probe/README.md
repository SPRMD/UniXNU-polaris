# PolarisA630Probe

This Darwin 23 component records the board resources needed for a future
Adreno 630 backend. It is deliberately a resource contract, not a GPU driver:
it does not map MMIO, change clocks or regulators, load `a630_*` firmware,
program the GMU/HFI, set up the SMMU, allocate DMA or expose a rendering
user-client.

## Provenance

Everything in `PolarisA630Board.h` and `research/polaris-a630-resources.json`
now comes from the **stock Polaris device tree**, read offline from the MIUI
boot image (representative entry: `Xiaomi Technologies, Inc. Polaris P2 v2.1`,
`qcom,sdm845-mtp`). The earlier revision of this component carried the same
numbers as *candidates* from a Linux DTS plus an MIUI report; those are retired
and the recorded values are what the firmware itself declares.

| Fact | Value | DT node |
| --- | --- | --- |
| GPU window | `0x05000000 + 0x40000` | `/soc/qcom,kgsl-3d0@5000000` |
| CX debug / CX misc | `0x05061000 + 0x800` / `0x0509e000 + 0x1000` | same, reg tuples 2 and 3 |
| Chip ID | `0x06030001` | `qcom,chipid` |
| GMU window | `0x0506a000 + 0x30000` | `/soc/qcom,gmu` |
| GMU PDC window | `0x0b200000 + 0x300000` | same, `kgsl_gmu_pdc_reg` |
| GPU SMMU | `0x05040000 + 0x10000` | `/soc/arm,smmu-kgsl@5040000` |
| GPUCC | `0x05090000 + 0x9000` | `/soc/qcom,gpucc@5090000` |
| GPU / HFI / GMU IRQ | SPI 300 / 304 / 305 | `interrupts` |
| SMMU global IRQ | SPI 229, 231 | `interrupts` |
| SMMU context IRQ | SPI 364..371 | `interrupts` |
| Stream IDs | 0 (user), 1 and 2 (secure) | `/soc/qcom,kgsl-iommu/*` `iommus` |

Two properties of that map matter to any future backend and are asserted by the
tests rather than smoothed over:

- The GPU SMMU window begins exactly where the kgsl window ends
  (`0x05040000 == 0x05000000 + 0x40000`).
- The GPUCC block is **nested inside** `kgsl_gmu_reg`, so the GMU window and the
  clock controller overlap. Each window must be mapped on its own terms; they
  are not disjoint carve-outs.

## What this still is not

A DT-declared chip ID is a firmware claim about the part, not a read from the
live GPU. `polaris-a630-chip-id-confirmed` therefore stays false, and the probe
never maps the GPU to check. The service is disabled unless the command line
contains `polaris-a630-probe=1`; it only publishes the matching DT nodes, their
`reg` ranges and the SID tuples. `darwin-driver-ready` remains false and the
package gate remains closed.

The local `references/unixnu-adreno6xx` component is an Adreno 642L / SM7325
(SM-T733) implementation. Its `native_adreno_a6xx_resources` contract is the
shape a Polaris backend would fill in, but none of its hardware procedures can
be reused without re-deriving them for SDM845's GPUCC, GMU, PAS13 and SMMU
state. That work has not started.

`PolarisA630Policy.h` provides the side-effect-free host and Darwin decision
model used by the probe. It can mark resource evidence internally consistent,
but its plan always keeps MMIO writes, firmware loading, DMA and SMMU
programming disabled until an independent temporary-boot report exists.
