# PolarisPmicRuntime

This is an experimental Darwin-side backend for the MIX 2S PM8998/PMI8998
path. It uses only the Qualcomm PMIC-arbiter v5 observer window and is disabled
unless the boot arguments explicitly request it:

- `polariskeys=1` enables PON/GPIO6 polling for power, volume-up and volume-down.
- `polarisbattery=1` enables the read-only fuel-gauge path.

The service never writes PMIC registers, changes GPIO configuration, clears an
interrupt, or claims a charger. A failed observer transaction disables its
lane. Battery data is published only after two matching PMIC revision reads and
range checks; otherwise the power source remains unknown.

The optional `polaris_buttons_set_sink` callback is the narrow bridge for a
future IOHID service. Without an IOHID sink the driver still records debounced
button masks in the registry and counters, but it cannot make iOS UI consume
the events.
