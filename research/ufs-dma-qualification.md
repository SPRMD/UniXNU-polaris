# Polaris UFS DMA / apps-SMMU qualification (2026-10-31)

Status: **NOT QUALIFIED**. No phone was connected, no register was read, no UFS
or SMMU write was performed, no runtime was started. The fail-closed guard in
`drivers/ShengUfs/PolarisDmaHandoff.h` is unchanged. This note turns the
"4 GiB+ DMA hard blocker" into a finite evidence problem with explicit pass/fail
criteria, and records what can and cannot be proven offline. Flashable and
hardware-tested gates are untouched.

Related:
- `drivers/ShengUfs/NativeUfs.cpp` (`hostBringUp`, runtime allocation and guard)
- `drivers/ShengUfs/PolarisDmaHandoff.h` (enforcement)
- `drivers/ShengUfs/ROOT-WINDOWS.md` (runtime contract)
- `drivers/DarwinBoot/README.md` (loader memory-range contract)
- `research/uefi-firmware-plan.md` (firmware provenance)
- `research/polaris_dma_qualification.py` (offline evidence evaluator; host-only)
- `research/ufs-dma-evidence-template.json` (record shape for a device run)

## 1. What the current tree actually enforces

Memory profile (unchanged): `scripts/make-polaris-adt.py` sets `dram-base =
0x100000000`, an upper-bank `dram-size` (0x7cc00000 for 6 GiB),
`darwinboot-memory-size = 0x40000000`, and
`darwinboot-memory-range = {0x100000000, dram_size}`. `drivers/DarwinBoot`
allocates the kernel window only inside the intersection of that range and a
real UEFI conventional-memory run. The 2026-10-24 phone boot measured that
handoff: `va=0xfffffff007004000 pa=0x100004000 owned=0x40000000`
(`NOTES.md:62-63`). Consequence: every `IOBufferMemoryDescriptor` allocation
available to `NativeUfs` is at or above 4 GiB.

The guard is **not** a literal "< 4 GiB" test. In
`NativeUfs::startBlock` -> `hostBringUp(runtime=true)`:

1. The DMA buffer is allocated with
   `IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,
   kIODirectionInOut | kIOMemoryPhysicallyContiguous | kIOMemoryMapperNone,
   kDmaBytes, 4096)`, then
   `polarisControllerDmaFits(phys, kDmaBytes, CAP)` bounds the buffer by
   UFSHCI CAP bit 24 (64AS): 64-bit when set, 32-bit otherwise.
2. `polarisDmaHandoff()` then reads live SMMU registers and requires all of:
   sCR0 CLIENTPD=0 and EXIDENABLE=0; IDR0.SMS=1; non-reserved IDR2
   IAS/OAS/UBS; the DMA range inside min(UBS, OAS) (and inside 32 bits when
   CAP[24]=0); exactly one VALID SMR per UFS stream ID in 0x100..0x10f with no
   overlap; S2CR TYPE=BYPASS for each; and unchanged CAP/IDR values on re-read.
3. If any step fails, the runtime returns false, logs the reason, and never
   submits a command or publishes media.

There is no separate hard-coded address check. The blocker is the absence of
recorded capability/state evidence: with no artifact for CAP[24] or IDR2/SMR/
S2CR under the current Renegade UEFI handoff, an allocation at or above 4 GiB
can only be refused, and this tree must not assume a passing read. That
wording is corrected in `ROOT-WINDOWS.md` by this change.

## 2. Offline evidence recorded in this round

Method: local read-only files only; DTB nodes parsed with a throwaway FDT parser
(no device, no MMIO). SHA-256 values are of the files as found on 2026-10-31.

| # | Artifact | SHA-256 / fact |
| --- | --- | --- |
| O1 | `polaris_unixnu_ios17_port/stock-boot-unpacked/polaris-dtb-tail.bin` (30,355,119 B, 65 FDTs, stock Android boot-image DTB table) | `277ab5d7...429442d`; every Polaris variant's `ufshc@1d84000` node has `compatible = "qcom,ufshc"`, `reg = <0x01d84000 0x2500>`, SPI 265, and **no `iommus` property** |
| O2 | same file | `apps-smmu@0x15000000` exists: `compatible = "qcom,qsmmu-v500"`, `reg = <0x15000000 0x80000>, <0x15080000 0x20>`, `#iommu-cells = <2>`, plus TBU children with `qcom,stream-id-range`; UFS is not attached to any stream there |
| O3 | `external/edk2-msm/Platform/Xiaomi/sdm845/FdtBlob_compat/polaris.dtb` (491,520 B, UEFI's own board DTB, model "Polaris P2 v2.1") | `47c16017...39dba8`; same UFS node, again **no `iommus`** |
| O4 | `external/edk2-msm/Platform/Qualcomm/sdm845/Apriori.fdf.inc` | `9e4b3a18...50ef5`; UFS and IOMMU at handoff are the **binary** DXEs `Platform/EFI_Binaries/Drivers/sdm845/UFSDxe/UFSDxe.efi` and `.../HALIOMMU/HALIOMMU.efi` (also in `dxe.fdf.inc`, `acc07656...0fa46`) |
| O5 | `external/edk2-msm/.gitmodules` | `bb8986a4...5c92a`; `Platform/EFI_Binaries` is submodule `github.com/edk2-porting/edk2-msm-binary.git`; **not checked out locally**, so UFSDxe/HALIOMMU behaviour is not source-auditable here |
| O6 | `external/edk2-msm/Platform/Qualcomm/sdm845/sdm845.dsc` | `d748d5db...9598e`; `PcdSystemMemoryBase=0x80000000`, `PcdSystemMemorySize=0xFDFA0000`, `PcdUefiMemPoolBase=0xA0000000`/size `0x2E000000`, framebuffer `0x9D400000`, DT store `0x83300000` |
| O7 | `external/edk2-msm/Silicon/Qualcomm/sdm845/Library/PlatformMemoryMapLib/PlatformMemoryMapLib.c` | `56990242...feed3e`; static low-bank layout, e.g. HLOS 4 `0x99100000+0x04230000` (Conv), Display Reserved `0x9D400000+0x02400000`, UEFI FD `0xCE000000+0x02000000`, DXE Heap `0xA0000000+0x2E000000` (Conv), above-4-GiB RAM partition `0xD0000000+...` (Conv, HOB-selected 4/6/8/10 GiB); SMMU MMIO `0x15000000+0xD0000` |
| O8 | `external/edk2-msm/configs/sdm845.conf` | `4c822e77...70acb`; `FD_BASE=0xCE000000`, `FD_SIZE=0x00700000` (firmware lives in the low bank) |
| O9 | mainline Linux `arch/arm64/boot/dts/qcom/sdm845.dtsi` (local ref copy) | `d93d27b0...f86eee` (matches `drivers/ShengUfs/README.md`); line 2630 `iommus = <&apps_smmu 0x100 0xf>`; line 5130 `apps_smmu: iommu@15000000`, reg `0x80000` |
| O10 | `external/UniXNU-polaris-upstream/research/polaris-ufs-port.md` (prior note, 2026-10-26) | claims the Qualcomm Android SDM845 tree assigns UFS stream `0x720`; **unverified here**, not used by any code |

What this proves: the two DTBs available for the board do **not** describe UFS
stream routing, and the UEFI components that would have written the active SMMU
state are closed-source binaries. What it does not prove: the current CAP value,
SMMU IDR/sCR0 state, SMR/S2CR routing, or where the vendor/UEFI chain left UFS.

Specification references used for the pass criteria (checked 2026-10-31):
- Linux v6.12 `include/ufs/ufshci.h`: `REG_CONTROLLER_CAPABILITIES = 0x00`,
  `MASK_64_ADDRESSING_SUPPORT = 0x01000000` (bit 24).
  `drivers/ufs/core/ufshcd.c:2414-2415` clears that capability under
  `UFSHCD_QUIRK_BROKEN_64BIT_ADDRESS`, i.e. the bit is the controller's
  address-width contract, not a suggestion.
- Linux v6.12 `drivers/iommu/arm/arm-smmu/arm-smmu.h`: IDR2 IAS/OAS/UBS fields
  (lines 70-72), SMR VALID/MASK/ID (101-103), S2CR TYPE bits 17:16 with
  TRANS=0/BYPASS=1/FAULT=2 and CBNDX (113-120), CBAR types (124-130), SCTLR.M
  bit 0 (154).
- Linux v6.12 `drivers/iommu/arm/arm-smmu/arm-smmu-qcom.c:311-333`: the
  Qualcomm bypass quirk. Firmware can leave a "BYPASS" write reading back as
  FAULT; Linux then reserves the last context bank, writes SCTLR=0 and
  CBAR.TYPE=S1_TRANS_S2_BYPASS, and routes bypass streams as TRANSLATE to that
  bank. `PolarisDmaHandoff.h` deliberately refuses that shape instead of
  guessing identity.
- ARM IHI 0062D.c (SMMUv2 / SMMU-500) and JEDEC JESD220 (UFS/UFSHCI), as
  already cited by the driver. `polarisPhysicalAddressBits()` maps IDR2 codes
  0..5 to 32/36/40/42/44/48 bits and treats 6..15 as **reserved** (no
  Linux-style default-to-48); `polarisUpstreamAddressBits()` maps UBS 5 to 49
  bits and 15 to 64 bits.

## 3. Evidence matrix and pass criteria

Each item is required unless marked otherwise. "Status" is the honest current
state; none of the device items is satisfied.

| ID | Evidence needed | Why it is needed | Where to obtain | Pass criterion | Status |
| --- | --- | --- | --- | --- | --- |
| E1 | Live UFSHCI CAP (0x00) and version (0x08) | CAP[24] decides whether any controller descriptor may carry an address >= 2^32 at all | Read-only register snapshot from one authorized boot; also confirm against the UFSHCI 3.x/2.x version | CAP[24]=1 for the high-DMA route; version consistent with the register set the driver uses | **missing**; requires user-authorized read-only device run |
| E2 | **High-DMA route only:** UTRD/UCD/PRDT high-address words accepted by hardware | Driver already writes UTRD+20 and PRDT+4 high words; the controller must actually consume them | Same snapshot plus a bounded transport test after E1/E3/E5 are proven; never as part of a flashable package | Command completes with OCS=0 using a buffer >= 2^32, and high words read back as written | **missing**; requires user-authorized device run |
| E3 | Which apps-SMMU instance is active and how it is clocked/powered for UFS | SDM845 has apps_smmu @0x15000000 (SMMU-500, qcom,qsmmu-v500) and a separate Adreno SMMU; a read of the wrong window proves nothing | Runtime snapshot of sCR0/IDR0/IDR1/IDR2 at 0x15000000; board DTB only names the node (O2/O3) | Registers respond, IDR0.SMS=1, sCR0 stable across the read, and the UFS master ID is associated with this SMMU by firmware evidence | **missing**; requires user-authorized read-only device run |
| E4 | SMMU capability: IDR0/IDR1/IDR2 (NUMSMRG, context banks, IAS/OAS/UBS, VA64) | Decides the addressable window and whether a 64-bit bypass route is even architecturally possible | Runtime read (read-only); cross-check against IHI 0062D.c; vendor DT `qcom,use-3-lvl-tables` is not width data | IDR2 codes decode (not reserved), VA64/geometry consistent; min(UBS,OAS) >= 33 bits for the high route (the low-pool route only needs the pool inside the 32-bit cap). SMMU capability alone does not prove the active route | **missing**; requires user-authorized read-only device run |
| E5 | Active sCR0 global state | CLIENTPD=0 (SMMU not globally bypassed) and EXIDENABLE=0 (no extended stream IDs) are preconditions for interpreting SMR/S2CR | Runtime read at 0x15000000 | CLIENTPD=0, EXIDENABLE=0, and unchanged over the whole read sequence | **missing**; requires user-authorized read-only device run |
| E6 | Active per-stream routing for the UFS master | The driver accepts only explicit identity bypass: one VALID SMR per stream ID, no overlaps, S2CR TYPE=BYPASS | Runtime read of all SMR/S2CR pairs the guard checks (0x100..0x10f); the SID set itself must be justified by firmware/DT/vendor evidence | Exactly one matching SMR per ID, no mask overlaps, S2CR TYPE=BYPASS for all, register values stable; no reliance on Qualcomm's BYPASS->FAULT quirk shape | **missing**; requires user-authorized read-only device run. The two local DTBs do not even name the SIDs (O1-O3), mainline claims 0x100/0xf (O9), a prior note claims 0x720 (O10, unverified) |
| E7 | Firmware handoff provenance | The UEFI that hands UFS over contains binary UFSDxe/HALIOMMU (O4-O5); we must pin exactly which firmware built the state and prove what it did | Fork build commit + resulting FD/boot-image SHA-256 (one known historical boot image: `534ebe68...`, NOTES.md:49), plus runtime powered/clocks/idle/outstanding-request snapshot | Firmware source+artifact pinned and matching the booted image; UFS powered and clocked; controller idle (UTRLDBR=0, UTRLRSR stopped, no outstanding request); no UFS MMIO use after handoff | **partial**: boot image hash recorded 2026-10-24, but not tied to a CAP/SMMU snapshot and the binary DXE build is not locally reproducible; the remaining snapshot requires user authorization |
| E8 | **High-DMA route only:** DMA ownership | A kernel buffer must be ours, physically contiguous, non-overlapping with the firmware request list, and cache-maintained | `IOBufferMemoryDescriptor` allocation record (address, contiguous length, allocator), UTRLBA/UTRLBAU, cache ops | Allocator is the kernel-task physically-contiguous path, allocation >= kDmaBytes (0x22000), 4 KiB aligned, contiguous, no overlap with [UTRLBA, +16 KiB], cache maintenance before/after each command | **missing**; requires user-authorized device run |
| E9 | **Low-pool route only:** owned low-address DMA pool (alternative route) | Removes the need for E1/E2 for the address axis, but must be genuinely owned memory | Loader allocation from UEFI `EfiConventionalMemory` below 2^32 + ADT record (see section 4) | Pool base+size inside 32 bits, page-aligned, >= kDmaBytes, allocated by our loader from UEFI conventional memory, recorded in the ADT, disjoint from firmware request list, UFS MMIO and known carve-outs, and passed to the driver exactly | **design only** (not implemented; no such ADT property exists) |
| E10 | Claim discipline | Prevent a test/CI result from becoming a fake readiness claim | This repository's manifest and `PolarisUfsWindowMediaReady` paths | No media/root readiness claim without an observed whole, non-writable IOMedia descendant; `flashable=false`, `hardware_tested=false` remain | **enforced by existing code/tests**; evaluator re-checks recorded claims |

Any single required `fail` refuses the route. `missing` means "not qualified
yet", never "probably fine". **Every device-side item is explicitly marked as
waiting for user authorization; this task performed zero device operations.**

## 4. Owned low-address DMA pool: design draft (not implemented)

Goal: give `NativeUfs` a DMA buffer below 4 GiB that is demonstrably ours,
without borrowing firmware pages and without weakening the SMMU guard.

### 4.1 Memory source

Preferred: at boot, DarwinBoot allocates one small pool with
`gBS->AllocatePages(AllocateAddress, EfiLoaderCode, ...)` from a
`EfiConventionalMemory` run below 2^32, using the same `GetMemoryMap`/
`RunEnd` logic it already uses for the kernel window
(`drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c` `AllocateWindow`).
A new optional ADT property, e.g.
`/chosen/darwinboot-dma-pool = {u64 base, u64 bytes, u64 map_epoch}`, is
filled by the loader with the address it actually reserved, and the driver
accepts it only if it is exact, in range, and still ours.

Rejected alternatives, with reasons:
- Reusing the firmware request list (UTRLBA) or any UEFI-owned page: not ours;
  the current probe reuse is diagnostic-only and explicitly forbidden for
  runtime.
- A hard-coded physical address in the ADT: a guess is not ownership; a
  collision with a carve-out would be undetectable and fatal.
- Lowering `dram-base` to expose low RAM to XNU: the low bank carries the
  firmware FD, DXE heap, XPU/TZ/PIL carve-outs (O6-O8); exposing it globally
  trades a UFS blocker for a memory-corruption class bug.
- Allocating from UEFI runtime services at driver time: ExitBootServices has
  already happened; runtime allocations are subject to firmware policy and
  cannot prove contiguity.
- Borrowing a "removed-dma-pool"/reserved region from the vendor DTB: reserved
  for firmware; no ownership proof and likely still used.

### 4.2 Driver-side contract (fail-closed)

Proposed acceptance in `NativeUfs` before any DMA (all must pass, all are
host-testable as pure logic; kernel code is **not** changed by this work):

1. The ADT property exists, has the exact expected size/version, and `bytes`
   equals the fixed requirement (kDmaBytes = 0x22000, 4 KiB aligned; a
   256 KiB/2 MiB rounding is allowed only if the extra bytes are declared).
2. `base + bytes <= 2^32` (inclusive last-byte check), `base % 4096 == 0`,
   and preferably 2 MiB aligned.
3. The pool does not overlap [UTRLBA, UTRLBA+16 KiB], the UFS MMIO window
   [0x01d84000, +0x2500), the SMMU MMIO window, or any range marked reserved
   in the boot chain's map snapshot.
4. The ADT records that the loader allocated the range from UEFI conventional
   memory (owner/provenance fields) and carries a hash of the memory-map
   snapshot it used; a stale/absent digest fails closed.
5. `PolarisDmaHandoff()` still runs for the SMMU routing/state conditions
   (E3-E6). The pool only removes E1/E2; it does not bypass SMMU
   qualification.
6. No firmware request-list page is used, no SMMU register is written, and on
   any failure the runtime returns false, logs the reason, and leaves
   `PolarisUfsWindowMediaReady` unset/false. No retry in the same boot (the
   allocation is pinned on first use, matching the existing single-shot rule).

### 4.3 Components that must change (ordered, each independently testable)

1. `drivers/DarwinBoot`: add the optional pool allocation property; refuse to
   boot with diagnostics if requested but unavailable (or strip the property
   and let the driver fail closed). Host test: reuse the existing ADT parser
   test pattern; no real allocation.
2. `scripts/make-polaris-adt.py`: emit the property placeholders and validate
   range/size; host test in the ADT suite.
3. `drivers/ShengUfs`: read/validate the property and use the pool; pure
   acceptance logic can live in a host-tested helper before it is wired to
   IOKit.
4. Packaging/CI: no manifest gate changes; the pool is not a hardware-success
   claim and does not make the package flashable.

### 4.4 Residual risks

- UEFI runtime services or a late DXE could still touch the range; the UEFI
  map snapshot plus boot-time allocation is the strongest local proof, but the
  firmware's own memory map is the trust anchor.
- Cache coherency: SDM845 UFS is `dma-coherent` in Linux DTs, but the pool's
  attributes must be confirmed by the record (shareability/MAIR path); the
  driver's `dc cvac`/`dc civac` calls are required regardless.
- A 32-bit controller with an owned pool can still fail if SMMU routing is
  wrong (E3-E6) or if the controller rejects the pool for another reason;
  transport failure remains possible and is not auto-recovered.
- No atomic multi-window allocation: keep one slot, else add a documented bump
  allocator and its tests.

## 5. Tooling: offline evaluator and record template

- `research/polaris_dma_qualification.py` evaluates a recorded JSON record
  against the same checks as the C++ guard plus the E8/E9 ownership rules.
  Verdicts: `qualified` / `refused` / `incomplete`; CLI exit 0/1/2. It never
  opens a device and never modifies the runtime policy. A `qualified` verdict
  only says "this record would satisfy the documented checks"; it is not a
  boot authorization.
- `research/ufs-dma-evidence-template.json` is the record shape; the shipped
  template evaluates as `incomplete` and can never be `qualified`.
- Host tests: `python -m unittest discover -s research -p 'test_*.py' -v`.
  The repository suite (`python -m unittest discover -s tests -q`) is
  unaffected and must stay green.

## 6. Next steps, dependency ordered

1. (done in this change) offline evidence matrix, corrected blocker wording,
   record template, host-tested evaluator.
2. Lead/integrator: decide how the evaluator and its tests enter the standard
   test command (they live under `research/` only because this task's write
   scope excluded `tests/`; moving `test_polaris_dma_qualification.py` under
   `tests/` is the recommended integration).
3. **Needs explicit user authorization**: one temporary, read-only diagnostic
   boot of a payload that only *reads* UFS CAP/VER, SMMU sCR0/IDR0/IDR1/IDR2
   and the 0x100..0x10f SMR/S2CR pairs, plus UTRLBA/UTRLDBR/UTRLRSR, renders
   the record to GOP and stops. No UFS/SMMU writes, no DMA ring takeover, no
   flashing. Feed the JSON to the evaluator; treat any missing field as
   missing.
4. If E1-E7 pass for the high route: re-enable the runtime (unchanged code
   path) and verify the whole IOMedia/APFS chain. If not, implement the pool
   path (section 4) through the owning components with tests.
5. Root identity/trust, APFS mount, Data and userland remain separate
   prerequisites; `flashable` and `hardware_tested` stay false, and
   `PolarisUfsWindowMediaReady` only ever reflects observed IOMedia.

## 7. Non-claims

- No CAP, SMMU IDR, sCR0, SMR, S2CR or stream ID for the current UEFI handoff
  is known; the values in old probe/panic comments (e.g. sCR0=0x002f0406,
  SID 0x60) are inherited historical notes from another chain, not Polaris
  Darwin 23 evidence.
- No low-address pool exists today; no ADT property encodes one.
- No host test can replace a register readback; passing tests here do not
  qualify hardware, root mount, or a flashable image.
