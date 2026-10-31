# PolarisHardwareServices

This is a Darwin 23 resource inventory service for the Xiaomi Mi MIX 2S
(`polaris`). It is deliberately smaller than a hardware driver. It walks the
device-tree objects already published by the platform provider and records
candidate resources for power keys, display, Synaptics touch, battery, Adreno,
Wi-Fi, Bluetooth, NFC and camera.

The service is inert unless the kernel command line contains
`polaris-hw-probe=1`. It never maps a register, enables a clock or regulator,
changes a GPIO, claims an interrupt, loads firmware, creates DMA mappings, or
touches UFS. Every published result is explicitly marked
`resource-only`/`darwin-driver-ready=false`. A matching DT node is evidence for
the next porting step, not proof that the corresponding iOS subsystem works.

The matcher accepts both the Qualcomm DT names used by the Polaris Linux/WOA
trees and the generic names found in the old ABL-shim diagnostics. This keeps
the inventory useful while the real Darwin transport layers are implemented.
The WiFi and Bluetooth match sets are disjoint: `wcn` is not a WiFi token,
because in the reference Polaris DTB only Bluetooth nodes carry it
(`bt_wcn3990`, the SLIMbus `wcn3990` slave), and matching it made the WiFi
count include Bluetooth nodes.

The checked-in board evidence gives the next driver stages these candidate
resources: Synaptics S3330 (`synaptics,dsx-i2c-force`) on QUPv3 SE14 at `0x20`
with IRQ GPIO 125 and reset GPIO 99; an NXP PN553-class `qcom,nq-nci` device on
SE3 at `0x28` with IRQ GPIO 63; QCA WCN3990 Bluetooth over UART; one of four
candidate DSI panels (JDI NT35596S, JDI R63452, EBBG FT8716, EBBG FT8719) whose
DT timing heights differ, so no single resolution is asserted here; Sony
IMX363 camera hardware as a candidate only (the DT carries no sensor identity);
and a PMI8998 fuel gauge. These values are inventory evidence only. The service does not assume
that a GPIO number is safe to drive or that a Linux/Android transport can be
called from Darwin.
