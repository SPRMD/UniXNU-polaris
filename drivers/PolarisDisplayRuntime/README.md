# Polaris CPU display runtime

This standalone kernel library implements synchronous CPU transfer from an
IOMemoryDescriptor into the firmware's inherited GOP scanout. It uses public
XNU IOKit interfaces, no private Apple framework addresses, private vtable
slots, static constructors, GPU registers, SDM710 code, or display queue edits.
The MobileFramebuffer compositor is **not connected** by this change.

## Exact integration requirements for the coordinating agent

No existing scripts, board/config/workflow/component manifests have been edited.
The following are integration work, not already performed changes:

1. Copy `drivers/GopFramebuffer/PolarisCpuScanout.{h,cpp}`,
   `drivers/PolarisDisplayRuntime/PolarisDisplayRuntime.{h,cpp}`, and
   `scripts/build-polaris-display.py` into the same paths in the resolved tree.
   Run the script **after the XNU bootstrap pass**, before the final kernel link:

   ```sh
   python3 scripts/build-polaris-display.py --root "$RESOLVED_TREE"
   ```

   It defaults to the real C++ record at
   `build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json`.
   An explicit `--record /absolute/path/to/record.json` is supported. Its
   compiler, working directory and include paths must exist on the build host.
   `--ar /absolute/path/to/llvm-ar` supports the Linux toolchain; otherwise the
   script uses `xcrun ar` or `llvm-ar`. There is no compiler fallback.

2. Link `build/polaris-display/libPolarisDisplayRuntime.a` into the final
   kernel along with an actual caller of `polaris_display_create` and
   `polaris_display_present`. Ordinary archive linkage is sufficient when the
   caller references these symbols. No constructor stripping, absolute-binding
   assembly or `OSMetaClass::preModLoad` is needed. This archive is **not** a
   substitute named `libNativeMobileDisplay.late.a` and has no kext personality.
   Keep the old ABI prototype from being instantiated as a functional display.
   Record `build-report.json` and the final link report; preserve existing
   kernel integrity sealing after the final link/patch pipeline.

3. In the board's sleepable, serialized IOKit startup path, supply a GOP nub
   whose device-memory index 0 is exactly the PE console physical base and
   `rowBytes * height` extent. The range must be physically contiguous and
   must remain firmware-owned scanout memory excluded from normal allocation.
   Do not hardcode the historical `0x9d400000` address. The board must verify
   actual GOP channel order: PE depth 32 does not establish BGRX. Only pass
   `POLARIS_SCANOUT_BGRX8888` after that audit. Opt-in boot argument is
   `polaris-cpu-display=1`; the root DT compatible list must include both
   `xiaomi,polaris` and `qcom,sdm845` as NUL-terminated strings.

4. Hold one `PolarisDisplayRuntime *` per owned scanout. Call
   `polaris_display_create(gopNub, verifiedFormat, &runtime)` once; failure
   leaves the output null. The coordinator must exclude concurrent creators
   and other console/framebuffer writers. There is deliberately no automatic
   startup hook or default boot enablement. Creation maps the framebuffer but
   does not draw a test pattern or claim it has appeared on the panel.

5. Call `polaris_display_present(runtime, descriptor, &layout, &transfer)` from
   the future audited compositor adapter (or a kernel bring-up producer). The
   descriptor must be a retained/owned, stable, CPU-readable **completed**
   linear frame, with length exactly `layout.bytes`, same width/height as GOP,
   and format BGRX8888. Source stride may differ. Hold the descriptor and
   runtime alive throughout the call; exclude producer writes until return.
   GPU fences/cache coherency must be satisfied by that producer: descriptor
   prepare and `dsb sy` do not wait for a GPU. Runtime performs prepare, rejects
   physical scanout aliases, maps read-only, copies visible pixels, unmaps and
   completes the descriptor. No user-supplied raw address is accepted.

6. On success, `transfer.sequence` advances and `transfer.bytes` counts visible
   pixel bytes (padding is untouched). Only then may an audited adapter retire
   its swap. These values describe CPU transfer completion, not hardware
   vsync/presentation. Failures zero the result; an error from descriptor
   completion can occur **after** pixel stores, so failure does not guarantee
   an unchanged screen. `polaris_display_stop` serializes against presents and
   makes later presents return not-ready. Drain all callers before
   `polaris_display_destroy`; concurrent destroy is unsupported.

The destination currently uses `kIOMapInhibitCache`. Performance, actual cache
attributes, existing aliases, console handover and firmware scanout continuity
need board qualification before trying a write-combined mapping. There is no
panel reinitialization, backlight control, suspend/resume, vblank interrupt,
refresh timer, scaling, rotation, color conversion, alpha composition or Metal.
The copy path is bounded to 64 MiB with dimensions at most 16384 each.

## Why the Legacy adapter was not copied wholesale

The local UniXNU reference has CPU transfer in
`NativeLegacyDisplay.cpp` / `NativeLegacyRequest.h`; NativeGOPPresenter also
has a separate descriptor-copy path. Sirius `build-native-legacy-display.py`
generates a 358-slot, 0x18a0-byte legacy-class adapter and binds fixed original
addresses. `package/LegacyDisplayProbe.cpp` combines its initialization with
Sirius GPU, HID and KeyStore hooks. None of these board hooks is reused here.

To connect iPadOS 17.7.11 compositor queues next, independently validate the
exact selected kernelcache/build UUID and SHA-256, prelink slide/address policy,
original IOMobileFramebufferLegacy ancestry/class extent and vtable, IOSurface
descriptor/format/plane/accessor ABI, swap request layout and lifetime,
activation/retirement locking, IOSurface admission and display registration.
Build label 21H461 alone is insufficient evidence for fixed addresses. Until
those inputs are audited, use the explicit descriptor entry point above.

## Provenance and verification

Local read-only references reviewed:

- UniXNU checkout `f0721e9745c45ad2600cd69c74730f1cca55d56a`,
  `drivers/GopFramebuffer/{NativeLegacyDisplay.cpp,NativeLegacyRequest.h,NativeGOPPresenter.cpp}`.
- UniXNU-sirius checkout `ac0c900485f3c0cd18de9707579a1cdcd3365503`,
  `scripts/build-native-legacy-display.py`, `package/LegacyDisplayProbe.cpp`.

Original online material fetched on 2026-10-31:

- https://unixnu.com/drivers/gop-framebuffer (HTTP 200; handoff, ABI and board-hook responsibilities).
- https://raw.githubusercontent.com/HuajiFruit/UniXNU-sirius/main/scripts/build-native-legacy-display.py
  (HTTP 200; inspected fixed bindings and constructor handling).
- The attempted raw UniXNU file URL using the local checkout revision returned
  HTTP 404. That local revision is provenance, not a verified online source pin.

Reproduce host checks from repository root:

```sh
python3 -B -m unittest discover -s tests -p test_build_polaris_display.py -v
clang++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined \
  drivers/GopFramebuffer/PolarisCpuScanout.cpp tests/polaris_cpu_scanout_test.cpp \
  -o /tmp/polaris-scanout-test
/tmp/polaris-scanout-test
```

The pixel executable passes 340 width/height/source-alignment combinations,
checks differing row padding, and rejects malformed layouts, overflow and
overlap without writes. Python tests cover compiler replay, malformed records,
Mach-O architecture/deployment/bounds, and static initializer rejection.
The coordinating agent reports both .cpp files passed cross-clang syntax
checking against actual CI headers using `scripts/check-darwin-sources.py`,
tree `/root/polaris-ci-headers-41179395488`, compiler
`/opt/unixnu-linux/llvm/bin/clang`; this is reported evidence, not a new test
run by this agent. Formal Darwin archive compilation and final linkage remain
pending CI. No phone was accessed; no real display usability is established.
Host checks do not simulate IOKit descriptor lifecycle, locking or mapping.
