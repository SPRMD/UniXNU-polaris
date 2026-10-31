# PolarisHidInput

This component is an opt-in bridge from the board-owned touch and PMIC sources to
 the original `IOHIDDevice` ABI used by the pinned iPadOS 17.7.11 (21H461)
 kernelcache. It can publish either a combined keyboard/consumer device or a
 touch-only digitizer when `polaris-touch-hid=1` or `polaris-touch-hid=2` is
 present.

The ABI is private and version-specific. The runtime refuses to start unless
`IOHIDFamily` loads and the live `IOHIDDevice` class size is 208 bytes. The source
and the absolute bindings are built only for the iPadOS-stage profile; the normal
source-kernel profile does not link this component. The touch source remains the
existing explicitly gated `polaris-touch-runtime=1` GPIO/I2C path, and buttons
arrive only through `PolarisPmicRuntime`'s read-only sink.

No Windows, Android, or proprietary binary is loaded. This is experimental:
`hardware_tested=false` and `flashable=false` remain mandatory until a GitHub
macOS build, prelinked boot, temporary boot, and per-event runtime logs pass.

The existing PolarisRuntime entry launches the HID probe; its launch claim is
atomic. The touch sink marks pending work, and the HID work-loop timer checks
pending/undelivered frames every 20 ms. Late event-driver matching, allocation
failure and report errors retain the last delivered contact set and retry the
same sequence. Sink unregister drains the callback before teardown. Registry
checkpoint work remains at one-second intervals.

The inherited edge-gesture vtable patch is disabled unless
`polaris-touch-edge-hook=1` is supplied. Its IOHIDEvent/IOHIDEventService slots
are not covered by the 207-slot IOHIDDevice audit. Even with the hook disabled,
the absolute IOHIDDevice bindings require the pinned prelinked image; the
208-byte runtime check alone does not establish ABI compatibility.

Lightweight regression tests (Linux/WSL with clang++):
`python3 -m unittest discover -s tests -p test_polaris_touch_hid_runtime.py -v`.
These execute production producer/consumer code with host stubs; they do not
validate hardware, IOKit scheduling, Apple linking or the final prelinked ABI.
