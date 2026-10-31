# PolarisRuntime

`PolarisRuntime` is the explicit Darwin-side start path for the Polaris
resource services.  The platform build links the individual services as
archives, so an `Info.plist` personality alone is not sufficient to make them
run in a source kernel.  The runtime calls their real IOKit `init/attach/start`
paths after the primary `ArmCpu` service is registered.

It is enabled only by `polaris-runtime=1`. The default payload enables this
gate together with the individual read-only probe gates. The runtime never
starts a service on a non-Polaris device and never enables a hardware backend
that has not supplied its own boot-argument gate. The services currently
publish board and protocol contracts only; this start path does not make
touch, buttons, battery, Wi-Fi, Bluetooth, NFC, camera, GPU, or display I/O
work by itself. `PolarisPeripheralContracts` is separately gated by
`polaris-peripheral-probe=1` and only publishes WCN/NCI/CCI resource facts and
codec self-test results. `PolarisNfcContract`, `PolarisCameraContract` and
`PolarisDisplayContract` are started only when their corresponding
`polaris-*-probe=1` argument is present; their runtime write/transport gates
remain closed.
