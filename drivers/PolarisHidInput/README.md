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
