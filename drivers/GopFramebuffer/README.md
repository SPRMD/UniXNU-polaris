# Polaris GopFramebuffer stage

This directory carries the UniXNU `NativeMobileDisplay` ABI adapter for the
Polaris GOP handoff. It is intentionally limited to read-only console metadata
and dimensions. It does not drive the Adreno 630 display controller, panel
power, backlight, refresh, or GPU composition.

The component is built only by `polaris_display_defconfig` and remains off in
the default platform configuration until an exact Darwin 23 ABI audit and a
temporary real-device boot qualify it.

## CPU scanout implementation (separate opt-in runtime)

`PolarisCpuScanout.cpp` now implements bounded CPU pixel transfer into an
inherited GOP framebuffer. It supports distinct source/destination strides,
unaligned source pixels and padded rows; it rejects invalid geometry, virtual
overlap and address overflow before writes. Only linear little-endian BGRX8888
is supported. The store barrier orders memory writes, not panel refresh.

The existing `NativeMobileDisplay` prototype above is unchanged. The new core
is built with `PolarisDisplayRuntime` by `scripts/build-polaris-display.py`, not
the existing NativeMobileDisplay recipe. See
[`../PolarisDisplayRuntime/README.md`](../PolarisDisplayRuntime/README.md) for
the exact runtime integration, host tests, remaining compositor dependencies,
and evidence limits. This is real CPU transfer code, not a working iPadOS UI.
