# PolarisSynapticsTouch

This Darwin 23 component is the board-gated touch stage for Xiaomi MIX 2S
(`polaris`). It accepts only a DT root containing `xiaomi,polaris` and
`qcom,sdm845`, and a child compatible with
`synaptics,dsx-i2c-force`. The source publishes the Polaris transport contract
(GPIO33/GPIO34 open-drain RMI4, address `0x20`, reset GPIO 99, 1080x2160) when
the boot argument `polaris-rmi4-touch=1` or `=2` is explicitly supplied.

The linked `PolarisTouchRuntime.c` is an opt-in experimental transport copied
from the previously hardware-tested Polaris chain and adapted to this tree. It
bit-bangs the known GPIO33/GPIO34 bus, checks the F01/F12 PDT identity, reads
bounded F12 frames, and publishes a seqlock for a future IOHID sink. It only
starts with `polaris-touch-runtime=1` (or the legacy `polaristouchhid=1`), and
`polaris-touch-reset=1` is separately required before it will release an
already asserted reset line. It restores both pads after every failure. It is
still marked experimental because this Darwin 23 tree has not yet produced an
independent temporary Polaris boot log for this runtime path and no HID sink is
prelinked.

The neighboring `SynapticsRmi4Protocol.h` contains bounded RMI4 PDT/F12
parsing, accepts release frames and only object type `1` active frames pending
runtime evidence, and can be host-tested independently.

The local WOA/EDK2 reference uses a Synaptics RMI4/S3708 path, while the retired
Polaris XNU 8796 chain reported an S3330. That identity mismatch is why this
component does not copy the EDK2 transport or claim hardware support.

