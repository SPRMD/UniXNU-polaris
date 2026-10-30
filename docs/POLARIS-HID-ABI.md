# Polaris HID ABI bridge

The cached source under `.cache/online-reference-20261031` records the original
`IOHIDDevice` vtable from the exact iPadOS 17.7.11 build used by this port
(`21H461`). The port preserves that evidence in `scripts/data/hid-device-abi.json`
and generates the opaque header and absolute bindings during the macOS
`polaris_ipados17_defconfig` build.

`PolarisHidInput` connects two already board-owned sources:

- `PolarisSynapticsTouch/PolarisTouchRuntime.c` publishes bounded RMI4 contact
  frames through a seqlock and sink callback.
- `PolarisPmicRuntime` publishes debounced PMIC button masks through its sink.

`polaris-touch-hid=1` requests a combined keyboard/consumer and digitizer HID
resource; `polaris-touch-hid=2` requests a touch-only resource. The bridge also
checks that `IOHIDFamily` loads and the live `IOHIDDevice` class is exactly 208
bytes before it registers the class. If those checks fail, it exits without
claiming input devices.

The bridge is not part of the normal source-kernel build. It is selected by
`CONFIG_XNU_POLARIS_HID_INPUT=y` in `polaris_ipados17_defconfig`, and remains
behind the runtime boot arguments above. No Android, Windows, or proprietary
binary is linked. Until the GitHub macOS build, a temporary Polaris boot, and
input-event logs pass, the contract remains `hardware_tested=false` and the
package remains `flashable=false`.
