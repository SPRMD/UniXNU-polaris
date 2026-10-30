# PolarisPmicInput

`PolarisPmicInput` is a Darwin 23 contract-only observer for the Xiaomi MIX 2S
(`polaris`, SDM845). It is disabled unless `polaris-pmic-input=1` is present in
the boot arguments. When enabled it checks the Polaris board identity, counts
candidate PMIC/SPMI nodes and publishes a bounded five-request observer plan.

The protocol header can be host-tested without a kernel or a phone. It accepts
only a small read allowlist for the PM8998/PMI8998 candidate peripherals,
decodes the candidate power/volume key levels, and converts a captured fuel
gauge sample. It never submits a request itself.

The Darwin service does not map MMIO, write SPMI, change GPIOs, claim an IRQ,
publish IOHID events or register an `IOPMPowerSource`. All state is explicitly
marked `read-only`, `darwin-driver-ready=false`. The values are a transport
contract based on the local Polaris Linux/WOA evidence; a real driver still
needs a temporary boot, a proven SPMI observer transport and per-event logs.
