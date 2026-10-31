/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef POLARIS_A630_BOARD_H
#define POLARIS_A630_BOARD_H

/*
 * SDM845/Polaris Adreno 630 board resources.
 *
 * Provenance: these are no longer candidates. Every window, interrupt and the
 * chip ID below were read from the stock Polaris device tree shipped in the
 * MIUI boot image (Xiaomi Polaris P2 v2.1, qcom,sdm845-mtp), nodes
 * /soc/qcom,kgsl-3d0@5000000, /soc/qcom,gmu, /soc/qcom,gpucc@5090000,
 * /soc/arm,smmu-kgsl@5040000 and /soc/qcom,kgsl-iommu. They describe what the
 * firmware declares, not what this tree has driven: no MMIO, GMU/HFI, ZAP,
 * firmware load or SMMU programming has been performed or is authorised.
 */

#define POLARIS_A630_GPU_BASE                 0x05000000ULL
#define POLARIS_A630_GPU_BYTES                0x00040000ULL
/* kgsl_3d0_cx_dbgc_memory: second reg tuple of the kgsl node. */
#define POLARIS_A630_GPU_CX_DBGC_BASE         0x05061000ULL
#define POLARIS_A630_GPU_CX_DBGC_BYTES        0x00000800ULL
#define POLARIS_A630_GPU_CX_MEM_BASE          0x0509e000ULL
#define POLARIS_A630_GPU_CX_MEM_BYTES         0x00001000ULL
#define POLARIS_A630_GMU_BASE                 0x0506a000ULL
#define POLARIS_A630_GMU_BYTES                0x00030000ULL
/* kgsl_gmu_pdc_reg: second reg tuple, the PDC block the GMU shares. */
#define POLARIS_A630_GMU_PDC_BASE             0x0b200000ULL
#define POLARIS_A630_GMU_PDC_BYTES            0x00300000ULL
#define POLARIS_A630_SMMU_BASE                0x05040000ULL
#define POLARIS_A630_SMMU_BYTES               0x00010000ULL
#define POLARIS_A630_GPUCC_BASE               0x05090000ULL
#define POLARIS_A630_GPUCC_BYTES              0x00009000ULL
#define POLARIS_A630_GCC_BASE                 0x00100000ULL
#define POLARIS_A630_GCC_BYTES                0x001f0000ULL
#define POLARIS_A630_PDC_BASE                 0x0b220000ULL
#define POLARIS_A630_PDC_BYTES                0x00000400ULL
#define POLARIS_A630_RSCC_BASE                0x0af20000ULL
#define POLARIS_A630_RSCC_BYTES               0x00001c44ULL

/* Raw GIC INTIDs: the DT spells them as SPI numbers, so add 32. */
#define POLARIS_A630_GPU_IRQ_SPI              300U
#define POLARIS_A630_GPU_IRQ_INTID            (POLARIS_A630_GPU_IRQ_SPI + 32U)
#define POLARIS_A630_GMU_HFI_IRQ_SPI          304U
#define POLARIS_A630_GMU_HFI_IRQ_INTID        (POLARIS_A630_GMU_HFI_IRQ_SPI + 32U)
#define POLARIS_A630_GMU_IRQ_SPI              305U
#define POLARIS_A630_GMU_IRQ_INTID            (POLARIS_A630_GMU_IRQ_SPI + 32U)
#define POLARIS_A630_SMMU_GLOBAL_IRQ0_SPI     229U
#define POLARIS_A630_SMMU_GLOBAL_IRQ1_SPI     231U
/* Eight per-context-bank interrupts, DT order 364..371. The node declares ten
 * interrupt entries in total; the other two are the global faults handled by
 * the SMMU_GLOBAL_IRQ pair above, not additional context banks. */
#define POLARIS_A630_SMMU_CONTEXT_IRQ_FIRST_SPI 364U
#define POLARIS_A630_SMMU_CONTEXT_IRQ_COUNT     8U

/*
 * Stream IDs, from the iommus tuples under /soc/qcom,kgsl-iommu:
 *   gfx3d_user   -> {phandle, 0}
 *   gfx3d_secure -> {phandle, 2} and {phandle, 1}
 * The phandle resolves to /soc/arm,smmu-kgsl@5040000, i.e. the GPU's own
 * SMMU instance, not the apps-SMMU that the UFS transport qualifies.
 */
#define POLARIS_A630_GPU_SID                  0U
#define POLARIS_A630_GPU_SECURE_SID_A         1U
#define POLARIS_A630_GPU_SECURE_SID_B         2U
#define POLARIS_A630_GPU_SID_COUNT            3U

/* qcom,chipid read from the stock DT: 0x06030001 (A630 rev 1). */
#define POLARIS_A630_CHIP_ID_REV0             0x06030000U
#define POLARIS_A630_CHIP_ID_REV1             0x06030001U
#define POLARIS_A630_CHIP_ID_DT_DECLARED      POLARIS_A630_CHIP_ID_REV1

/* qcom,initial-pwrlevel = 6; the GPU boots at the level the DT selects. */
#define POLARIS_A630_DT_INITIAL_PWRLEVEL      6U

/*
 * Firmware regions the DT reserves. gpu_region is a removed-dma-pool, i.e.
 * carved out for the GPU's own use and never handed to the kernel allocator;
 * pil_spss_region is the secure PIL image area for the GPU subsystem.
 */
#define POLARIS_A630_GPU_REGION_BASE          0x8c415000ULL
#define POLARIS_A630_GPU_REGION_BYTES         0x00002000ULL
#define POLARIS_A630_PIL_SPSS_BASE            0x97f00000ULL
#define POLARIS_A630_PIL_SPSS_BYTES           0x00100000ULL

#endif
