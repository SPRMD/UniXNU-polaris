# Polaris GopFramebuffer stage

This directory carries the UniXNU `NativeMobileDisplay` ABI adapter for the
Polaris GOP handoff. It is intentionally limited to read-only console metadata
and dimensions. It does not drive the Adreno 630 display controller, panel
power, backlight, refresh, or GPU composition.

The component is built only by `polaris_display_defconfig` and remains off in
the default platform configuration until an exact Darwin 23 ABI audit and a
temporary real-device boot qualify it.
