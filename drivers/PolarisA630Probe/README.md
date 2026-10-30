# PolarisA630Probe

This Darwin 23 component records the board resources needed for a future
Adreno 630 backend.  It is deliberately a resource contract, not a GPU driver:
it does not map MMIO, change clocks or regulators, load `a630_*` firmware,
program the GMU/HFI, set up the SMMU, allocate DMA or expose a rendering
user-client.

The resource names and the A630-family firmware set come from the local
`references/UniXNU-sirius` A6xx bring-up and the Polaris DT resource inventory.
The Sirius code is an A615/A630-family experiment and cannot be copied as a
Polaris backend without checking the Polaris GPUCC, GMU, PAS13 and SMMU state.

The service is disabled unless the command line contains
`polaris-a630-probe=1`.  It only publishes the matching DT nodes and their
`reg` ranges.  `darwin-driver-ready` remains false and the package gate remains
closed.  The Polaris candidate trees report chip IDs `0x06030000` and
`0x06030001`; the probe records both as candidates and deliberately does not
claim that either revision was read from the live GPU.
