#!/usr/bin/env python3
"""Assemble the polaris iOS-stage ESP FAT image (mtools, no mounting).

Contents: UniXNU boot manager as BOOTAA64.EFI, the DarwinBoot loader, the
prelinked kernel with its iPad-identity ADT, the trust-cache bundle and the
unixnu.toml entry. Parameters follow the sheng payload conventions (prelink
era): serial=0 (no UART), the platform memory window, cpus=1.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

TOML = '''version = 1
[boot]
timeout = 3
[kits]
autoload = false
[[driver]]
path = "Payloads/DarwinBoot.efi"
[[entry]]
id = "ios"
title = "polaris: iPadOS 17 userland"
type = "xnu"
path = "Payloads/kernel.macho"
args = "-v serial=0 debug=0x14e kt_fixed_zones=120 cpus=1 native-ufs-root=1 polaris-runtime=1 polaris-board-probe=1 polaris-hw-probe=1 polaris-pmic-input=1 polaris-rmi4-touch=1 polaris-transport-probe=1 polaris-peripheral-probe=1 polaris-nfc-probe=1 polaris-camera-probe=1 polaris-a630-probe=1 polaris-display-probe=1 -no_slto_panic"
'''


def render_toml(ipados_stage: bool) -> str:
    """Render the boot entry, enabling experimental input only for iPadOS.

    The ordinary platform image remains a read-only bring-up profile. The
    iPadOS stage has the pinned IOHID bridge and the revision-gated PMIC
    services linked, so it may request them explicitly; each service still
    fails closed if its runtime contract is absent.
    """
    if not ipados_stage:
        return TOML
    extra = " polaris-touch-hid=1 polariskeys=1 polarisbattery=1"
    return TOML.replace("polaris-display-probe=1 -no_slto_panic",
                        "polaris-display-probe=1" + extra + " -no_slto_panic")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True, help='prelinked kernel.macho')
    parser.add_argument('--adt', type=Path, required=True, help='iPad-identity ADT')
    parser.add_argument('--trust', type=Path, required=True, help='trust bundle from make-trust-bundle.py')
    parser.add_argument('--efi', type=Path, required=True, help='EFI build output as produced by check-efi.py')
    parser.add_argument('--out', type=Path, default=ROOT / 'out/ios-esp/ios-esp.img')
    parser.add_argument('--tree', type=Path,
                        help='optional directory copy of the exact FAT tree used for the image')
    parser.add_argument('--ipados-stage', action='store_true',
                        help='request the experimental HID, key and battery services')
    parser.add_argument('--probe', default=None,
                        help='patch boot-progress probes into the ESP kernel copy: '
                             '"panic" draws panic() text on screen; otherwise pass '
                             'patch-xnu-entry-probe.py arguments (e.g. "--no-reset")')
    parser.add_argument('--no-probe', action='store_true',
                        help='never patch the ESP kernel copy')
    args = parser.parse_args()

    efi = args.efi.resolve()
    files = {
        'EFI/BOOT/BOOTAA64.EFI': efi / 'efi/Build/Out/AARCH64-DEBUG/UniXNU.efi',
        'EFI/UniXNU/Payloads/DarwinBoot.efi': efi / 'loader/build/DarwinBoot/DEBUG_GCC/AARCH64/DarwinBoot.efi',
        'EFI/UniXNU/Payloads/kernel.macho': args.kernel.resolve(),
        'EFI/UniXNU/Payloads/kernel.macho.adt': args.adt.resolve(),
        'EFI/UniXNU/Payloads/kernel.macho.trustcache': args.trust.resolve(),
        'EFI/UniXNU/unixnu.toml': None,
    }
    for name, path in files.items():
        if path is not None and not path.is_file():
            raise SystemExit(f'missing input: {path}')

    report_path = args.kernel.with_suffix('.json')
    if not report_path.is_file():
        raise SystemExit(f'missing prelinked kernel report: {report_path}')
    try:
        report = json.loads(report_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f'invalid prelinked kernel report: {report_path}: {error}')
    if report.get('kernel_sha256') != hashlib.sha256(args.kernel.read_bytes()).hexdigest():
        raise SystemExit('prelinked kernel does not match its kernel.json report')
    if report.get('original_components_prelinked') is not True:
        raise SystemExit('iOS-stage ESP requires kernel-prelinked.macho with original components')
    if report.get('final_configured_link_passed') is not True:
        raise SystemExit('iOS-stage ESP requires a successful final configured kernel link')

    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    # The probes are applied to a private copy. The input kernel artifact and
    # the prelinked-kernel report that describes it must keep matching, so
    # patching in place would break the hash check above and corrupt the
    # artifact for every later consumer. A kernel whose layout the probe tool
    # cannot verify makes the tool exit non-zero, so a diagnostic-only patch
    # can never ship silently broken.
    kernel_path = args.kernel.resolve()
    if args.probe and not args.no_probe:
        import shlex
        import tempfile
        probe = ROOT / 'scripts/patch-xnu-entry-probe.py'
        extra = ['--panic-screen'] if args.probe == 'panic' else shlex.split(args.probe)
        staged = Path(tempfile.mkdtemp(prefix='ios-esp-probe-')) / 'kernel.macho'
        shutil.copyfile(kernel_path, staged)
        subprocess.run([sys.executable, str(probe), str(staged), *extra], check=True)
        # A source corecrypto build carries a 32-byte POST HMAC field that the
        # rewritten __text invalidates, so it has to be resealed over the patched
        # copy. This stage runs the prelinked bootstrap instead
        # (CONFIG_XNU_CRYPTO_BOOTSTRAP="prelinked"): there is no such field and no
        # source provider to reseal, and the sealer refuses the image rather than
        # invent one. Skip only when the field is genuinely absent, so a future
        # config that does carry it still gets sealed.
        if b'_source_corecrypto14_bootstrap\x00' in staged.read_bytes():
            subprocess.run([sys.executable, str(ROOT / 'scripts/seal-source-crypto-kernel.py'),
                            str(staged)], check=True)
        else:
            print('no source corecrypto bootstrap in this kernel: nothing to reseal')
        kernel_path = staged
        print('probed kernel copy:', staged)
    files['EFI/UniXNU/Payloads/kernel.macho'] = kernel_path
    tree = args.tree.resolve() if args.tree else None
    if tree and tree.exists():
        shutil.rmtree(tree)
    if tree:
        for name, path in files.items():
            target = tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if path is None:
                target.write_text(render_toml(args.ipados_stage), encoding='utf-8')
            else:
                shutil.copyfile(path, target)
    subprocess.run(['truncate', '-s', '256M', str(out)], check=True)
    subprocess.run(['mformat', '-i', str(out), '-v', 'POLARISESP', '::'], check=True)
    made = {'/'}
    for name in files:
        parts = name.split('/')[:-1]
        current = ''
        for part in parts:
            current += '/' + part
            if current not in made:
                subprocess.run(['mmd', '-i', str(out), f'::{current}'], check=True)
                made.add(current)
    for name, path in files.items():
        target = f'::{name}'
        if path is None:
            subprocess.run(['mcopy', '-i', str(out), '-', target],
                           input=render_toml(args.ipados_stage).encode(), check=True)
        else:
            subprocess.run(['mcopy', '-i', str(out), str(path), target], check=True)
    listing = subprocess.run(['mdir', '-i', str(out), '-/', '::'], capture_output=True, text=True, check=True).stdout
    print(listing)
    report = {'image': str(out), 'image_bytes': out.stat().st_size,
              'kernel_sha256': hashlib.sha256(kernel_path.read_bytes()).hexdigest(),
              'input_kernel_sha256': hashlib.sha256(args.kernel.read_bytes()).hexdigest(),
              'probe': (args.probe if (args.probe and not args.no_probe) else None),
              'trust_sha256': hashlib.sha256(args.trust.read_bytes()).hexdigest(),
              'tree': str(tree) if tree else None,
              'boot_profile': 'ipados-stage' if args.ipados_stage else 'platform',
              'experimental_input_services': bool(args.ipados_stage),
              'flash_command': f'fastboot flash <esp-partition> {out}'}
    out.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print('done:', out)


if __name__ == '__main__':
    main()
