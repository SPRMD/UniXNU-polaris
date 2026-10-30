# Polaris EDK2 driver evidence for Darwin ports

The local reference checkout `device-repo/UniXNU-polaris/.cache/reference/edk2-msm-full`
contains board-specific EDK2 implementations.  They are useful for resource
names, protocol order and timing, but they are UEFI drivers and cannot be
linked into XNU.

The Polaris Synaptics RMI4 source is under
`Silicon/Qualcomm/QcomPkg/Drivers/SynapticsRmi4Dxe/`.  Its bounded bring-up
sequence is:

1. Open the QUPv3 I2C controller and power the controller GPIO rails.
2. Drive the reset GPIO low, wait 2 ms, drive it high and wait 200 ms.
3. Read six-byte RMI4 PDT entries from `0xE9` downward, changing pages at the
   page terminator, and locate Function 12.
4. Change to the F12 page, read an eight-byte contact record, and expose the
   first contact through UEFI Absolute Pointer.  The reference polls every
   100 ms and closes the I2C handle at ExitBootServices.

The Polaris camera ASL is under
`Platform/Xiaomi/sdm845/AcpiTables/polaris/cust_camera_exasoc*.asl`.  The rear
Sony IMX363 candidate uses I2C slave information `0x00050034` (7-bit address
`0x34`, fast-mode 400 kHz), probes register `0x0016` for sensor ID `0x0363`,
and names the tuning files `com.qti.sensormodule.imx363.bin` and
`com.qti.tuned.semco_imx363.bin`.  The recorded power sequence includes
camera clocks, TLMM GPIOs 80/87/102/21, PMIC GPIO10, the PMIC LVS1 1.8 V rail,
MCLK0 at 24 MHz, reset release and an 18 ms settle delay.

These values are board evidence only.  A Darwin implementation still needs a
QUPv3/IOHID or CCI/CSIPHY/CSID backend, board ownership checks, bounded error
handling and a temporary Polaris boot before its subsystem gate can be opened.
