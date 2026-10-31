# DarwinBoot for polaris

Based on UniXNU/DarwinBoot `12bc9e23fb5f9a7d2715a9e30c021a883db0a310`
(inherited from the sweet device port of the same override).
The complete Darwin 23 boot_args ABI comes from upstream.

The added optional `/chosen/darwinboot-memory-range` is a little-endian
pair of u64 values `{physical_base, bytes}`. It constrains allocation to
the intersection of that range with a real UEFI conventional-memory run.
Page alignment, nonempty size, addition overflow, property size, placement
and duplicates are checked. An allocation failure never falls back outside
the range. An omitted property retains the upstream unrestricted policy.

polaris supplies the upper DDR bank, by default `0x100000000 + 0x7cc00000`
(the 6 GiB variant, safe on both installed sizes; the 8 GiB variant uses
`0xfcc00000`), above the low-bank Qualcomm XPU carve-outs. This replaces the
old ABL-shim chain's fixed kernel placement. The constraint does not
establish that a polaris UEFI port has a correct memory map, nor that its
largest free run can hold the requested kernel window. No polaris UEFI
firmware exists yet; physical validation is pending.

## Optional low-address DMA pool

`/chosen/darwinboot-dma-pool-size` (u64 bytes) and `/chosen/darwinboot-dma-pool`
(16 zero bytes) are a matched pair. When the ADT declares both, `AllocateDmaPool`
reserves that many bytes **below 4 GiB** from the real UEFI conventional-memory
map and writes the reserved `{base, bytes}` back into the slot. When the ADT
declares neither, nothing changes. When the ADT declares only one, or the pool
cannot be reserved inside the 32-bit window, the loader **refuses to boot**; it
never relocates the pool above 4 GiB and never falls back to a kernel-window
address.

Why: the kernel window comes from the upper bank (>= 4 GiB), so every kernel
`IOBufferMemoryDescriptor` lands above 4 GiB. A bus master that cannot be shown
to address those addresses cannot use those buffers. A pool the loader really
owns removes the *address* axis only — it says nothing about SMMU routing, and
`polarisDmaHandoff()` still evaluates the pool address before any command is
submitted.

Bounds (`DmaPool.h`, mirrored in `scripts/make-polaris-adt.py` and
`drivers/ShengUfs/PolarisDmaPool.h`): 64 KiB .. 4 MiB, 4 KiB aligned, entirely
below `0x100000000`, never overlapping the kernel window. Request it with:

```sh
python3 scripts/make-polaris-adt.py --output out/polaris.adt --include-ufs \
  --dma-pool-size 0x40000
```

The standalone DSC builds only the loader driver. Upstream's separate
Validation application is not included in this device override.
