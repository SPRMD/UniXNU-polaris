# Polaris iPadOS 17 stage

The repository now has a host-only assembly path for the experimental iPadOS
17 stage:

1. `build-platform-kernel.py --defconfig polaris_ipados17_defconfig` builds
   the Darwin 23 source kernel and the optional storage ABI archive.
2. `make-trust-bundle.py` combines the OS and SystemOS trust caches from a
   locally supplied IPSW.
3. `make-ios-esp.py` creates the FAT ESP containing `BOOTAA64.EFI`,
   `DarwinBoot.efi`, the prelinked kernel, the Polaris ADT candidate and the
   trust bundle.
4. `make-userdata-linux.py --partition darwin` creates the SHNGROOT image for
   the separate `darwin` partition while the ESP remains in `userdata`.
5. `build-ios-stage.py` joins those outputs and can pass them to
   `make-polaris-package.py`.

Every generated package remains `flashable=false` until an independent
temporary-boot report proves that the exact kernel, ADT, UFS root handoff and
userland work on a real 6 GiB/128 GiB Polaris. The scripts do not access adb,
fastboot or a phone. Android and WOA firmware metadata remains evidence only;
it is not copied into Darwin as a driver.

The package can carry `darwin-root.img` and the guarded installer knows the
partition name, but the guarded installer refuses to write while any required
gate is open. This is intentional because the current storage source is still
a bring-up path and the GPU, Wi-Fi, Bluetooth, NFC and camera backends have not
been hardware qualified.
