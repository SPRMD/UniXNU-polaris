# Polaris Synaptics RMI4 protocol reference

This directory contains a **host-side protocol reference only**. It does not
register an IOKit service and does not touch I2C, GPIO, interrupts, MMIO, DMA,
firmware, or the phone. It is a small executable specification for the next
Darwin 23 touch-driver stage:

- walk six-byte RMI4 PDT descriptors downward from `0xE9`;
- locate F12 without reading beyond a bounded page snapshot; and
- decode the eight-byte single-contact sample used by the checked-in
  `edk2-msm` `SynapticsRmi4Dxe` reference (`status`, little-endian X, and
  little-endian Y).

A zero status is represented as a valid release frame. Only low-nibble object
type `1` is accepted as an active contact until runtime evidence establishes
another type; active samples can then be checked against inclusive coordinate
bounds. The final three bytes remain
opaque because their meaning is not established by this reference.

The repository's Polaris contract remains `touch: research-only/disabled`.
The WOA/EDK2 material identifies an RMI4/S3708 path, while the retired XNU
8796 chain reported S3330; the exact controller identity and this byte layout
still require Darwin 23 compilation and a user-approved temporary-boot test.
