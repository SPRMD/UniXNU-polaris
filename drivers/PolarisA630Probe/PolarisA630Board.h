/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef POLARIS_A630_BOARD_H
#define POLARIS_A630_BOARD_H

/* Static SDM845/Polaris facts from the local Linux DTS and MIUI DT report. */
#define POLARIS_A630_GPU_BASE                 0x05000000ULL
#define POLARIS_A630_GPU_BYTES                0x00040000ULL
#define POLARIS_A630_GPU_CX_MEM_BASE         0x0509e000ULL
#define POLARIS_A630_GPU_CX_MEM_BYTES        0x00001000ULL
#define POLARIS_A630_GMU_BASE                 0x0506a000ULL
#define POLARIS_A630_GMU_BYTES                0x00030000ULL
#define POLARIS_A630_SMMU_BASE                0x05040000ULL
#define POLARIS_A630_SMMU_BYTES               0x00010000ULL
#define POLARIS_A630_GPUCC_BASE               0x05090000ULL
#define POLARIS_A630_GPUCC_BYTES              0x00009000ULL

/* GIC SPI candidates from qcom,adreno-630.2 / adreno-gmu-630.2. */
#define POLARIS_A630_GPU_IRQ_SPI              300U
#define POLARIS_A630_GMU_HFI_IRQ_SPI          304U
#define POLARIS_A630_GMU_IRQ_SPI              305U
#define POLARIS_A630_SMMU_GLOBAL_IRQ0_SPI     229U
#define POLARIS_A630_SMMU_GLOBAL_IRQ1_SPI     231U

#define POLARIS_A630_CHIP_ID_REV0             0x06030000U
#define POLARIS_A630_CHIP_ID_REV1             0x06030001U

#endif
