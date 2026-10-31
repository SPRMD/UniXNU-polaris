#!/usr/bin/env python3
"""Compile a platform archive using the actual Darwin 23 XNU compile record.

Used inside the assembled UniXNU tree. Runs the recorded compiler and xcrun
ar; writes only build/<component>/. Does not access a device.
"""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import shutil

ROOT = Path(__file__).resolve().parents[1]

# These initializers are explicitly called inside OSMetaClass::preModLoad /
# postModLoad by PolarisRuntime. They must not also run as automatic globals.
RUNTIME_CLASSES = {
    'PolarisBoardProbe', 'PolarisHardwareServices', 'PolarisPmicInput',
    'PolarisPmicRuntime', 'PolarisSynapticsTouch', 'PolarisTransportContracts',
    'PolarisPeripheralContracts', 'PolarisNfcContract', 'PolarisCameraContract',
    'PolarisDisplayContract', 'PolarisA630Probe',
}


def llvm_tool(name):
    found = shutil.which(name)
    if found:
        return found
    for prefix in ('/opt/homebrew/opt/llvm/bin', '/usr/local/opt/llvm/bin'):
        candidate = Path(prefix) / name
        if candidate.is_file():
            return str(candidate)
    raise SystemExit(f'{name} required to export late IOKit initializers')


def late_initializer_object(source, destination):
    late = destination.with_suffix('.late.o')
    symbol = '__GLOBAL__sub_I_' + source.name
    subprocess.run([llvm_tool('llvm-objcopy'), '--remove-section=__DATA,__mod_init_func',
                    '--globalize-symbol=' + symbol, str(destination), str(late)], check=True)
    exported = subprocess.check_output(
        [llvm_tool('llvm-nm'), '--defined-only', '--extern-only', str(late)], text=True)
    if not any(line.split()[-1:] == [symbol] for line in exported.splitlines()):
        raise SystemExit(f'initializer was not exported: {symbol}')
    return late


def rewrite_compile_command(record, source, destination):
    """Replace input/output and remove warning flags without orphaning -Xclang."""
    command = []
    arguments = record['arguments']
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value in ('-o', '-Xclang'):
            if index + 1 >= len(arguments):
                raise ValueError(f'missing argument after {value}')
            following = arguments[index + 1]
            if value == '-o':
                command.extend(['-o', str(destination)])
            elif not is_warning_flag(following):
                command.extend([value, following])
            index += 2
            continue
        if value == record['file']:
            command.append(str(source))
        elif not is_warning_flag(value):
            command.append(value)
        index += 1
    return command


def is_warning_flag(value):
    # Preserve driver forwarding flags: -Wl, -Wa, and -Wp, are not warnings.
    return value.startswith('-W') and not value.startswith(('-Wl,', '-Wa,', '-Wp,'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=['ArmDTPlatform', 'ArmCpu', 'ShengUfs', 'PolarisBoardProbe', 'PolarisHardwareServices', 'PolarisPmicInput', 'PolarisPmicRuntime', 'PolarisSynapticsTouch', 'PolarisTransportContracts', 'PolarisPeripheralContracts', 'PolarisNfcContract', 'PolarisCameraContract', 'PolarisA630Probe', 'PolarisDisplayContract', 'PolarisRuntime', 'NativeMobileDisplay'])
    parser.add_argument('--ufs-block-runtime', action='store_true',
                        help='compile experimental read-only LUN backend (still boot-arg gated)')
    parser.add_argument('--with-hid-runtime', action='store_true',
                        help='link PolarisRuntime to the selected private HID bridge')
    args = parser.parse_args()
    if args.ufs_block_runtime and args.component != 'ShengUfs':
        parser.error('--ufs-block-runtime applies only to ShengUfs')
    if args.with_hid_runtime and args.component != 'PolarisRuntime':
        parser.error('--with-hid-runtime applies only to PolarisRuntime')
    output_names = {
        'ArmCpu': ('armcpu', 'ArmCpu', 'ArmCpu'),
        'ArmDTPlatform': ('armdt-platform', 'ArmDTPlatform', 'ArmDTPlatform'),
        # The component manifest links the archive as libShengUfs.a while the
        # runtime class and source file retain the historical NativeUfs name.
        'ShengUfs': ('sheng-ufs', 'NativeUfs', 'ShengUfs'),
        'PolarisBoardProbe': ('polaris-board-probe', 'PolarisBoardProbe', 'PolarisBoardProbe'),
        'PolarisHardwareServices': ('polaris-hardware-services', 'PolarisHardwareServices', 'PolarisHardwareServices'),
        'PolarisPmicInput': ('polaris-pmic-input', 'PolarisPmicInput', 'PolarisPmicInput'),
        'PolarisPmicRuntime': ('polaris-pmic-runtime', 'PolarisPmicRuntime', 'PolarisPmicRuntime'),
        'PolarisSynapticsTouch': ('polaris-synaptics-touch', 'PolarisSynapticsTouch', 'PolarisSynapticsTouch'),
        'PolarisTransportContracts': ('polaris-transport-contracts', 'PolarisTransportContracts', 'PolarisTransportContracts'),
        'PolarisPeripheralContracts': ('polaris-peripheral-contracts', 'PolarisPeripheralContracts', 'PolarisPeripheralContracts'),
        'PolarisNfcContract': ('polaris-nfc-contract', 'PolarisNfcContract', 'PolarisNfcContract'),
        'PolarisCameraContract': ('polaris-camera-contract', 'PolarisCameraContract', 'PolarisCameraContract'),
        'PolarisA630Probe': ('polaris-a630-probe', 'PolarisA630Probe', 'PolarisA630Probe'),
        'PolarisDisplayContract': ('polaris-display-contract', 'PolarisDisplayContract', 'PolarisDisplayContract'),
        'PolarisRuntime': ('polaris-runtime', 'PolarisRuntime', 'PolarisRuntime'),
        # The Darwin 23 link script consumes the late display archive. The
        # Polaris stage only uses the read-only GOP metadata adapter; it does
        # not claim panel, backlight, Adreno, or composition support.
        'NativeMobileDisplay': ('gop-framebuffer', 'NativeMobileDisplay', 'GopFramebuffer'),
    }
    out_name, source_name, archive_name = output_names[args.component]
    out = ROOT / 'build' / out_name
    recipe = ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
    record = json.loads(recipe.read_text().strip().rstrip(','))
    source_dir = ROOT / 'drivers' / ('GopFramebuffer' if args.component == 'NativeMobileDisplay' else args.component)
    source = source_dir / (source_name + '.cpp')
    destination = out / (args.component + '.o')
    out.mkdir(parents=True, exist_ok=True)
    command = rewrite_compile_command(record, source, destination)
    if args.component == 'PolarisRuntime':
        command.append('-DPOLARIS_WITH_HID_RUNTIME=' + str(int(args.with_hid_runtime)))
    command.extend(['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-Wno-c99-designator', '-Wno-reorder-init-list',
                    '-Wno-deprecated-enum-enum-conversion',
                    '-I', str(ROOT / '.cache/xnu-work/osfmk'),
                    '-I', str(source.parent)])
    if args.component == 'ShengUfs' and args.ufs_block_runtime:
        # Standalone archive builds must also refresh/check the pinned ABI.
        subprocess.run(['python3', str(ROOT / 'scripts/prepare-storage-headers.py')], check=True)
        command.extend(['-I', str(ROOT / 'build/storage-abi/include'),
                        '-DPOLARIS_UFS_BLOCK_RUNTIME=1', '-mgeneral-regs-only'])
    (out / 'compile-command.json').write_text(json.dumps(command, indent=2) + '\n')
    result = subprocess.run(command, cwd=record['directory'], capture_output=True, text=True)
    (out / 'compile.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    data = destination.read_bytes()
    if struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 1):
        raise SystemExit('Expected a plain ARM64 Mach-O object')
    offset = 32
    deployment = None
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, length = struct.unpack_from('<II', data, offset)
        if cmd == 0x32:
            deployment = struct.unpack_from('<II', data, offset + 8)
        offset += length
    if deployment != (2, 0x110000):
        raise SystemExit(f'Expected iOS 17 deployment, got {deployment}')
    archive = out / ('lib' + archive_name + '.a')
    archive.unlink(missing_ok=True)
    linked_object = late_initializer_object(source, destination) if args.component in RUNTIME_CLASSES else destination
    subprocess.run(['xcrun', 'ar', 'rcs', archive, linked_object], check=True)
    if args.component == 'NativeMobileDisplay':
        # build-xnu-4k-baseline.sh links the post-ABI display archive. Keep a
        # byte-for-byte late copy and a small report so the link can verify the
        # exact source/object that was built in this tree.
        late_object = out / 'NativeMobileDisplay.late.o'
        late_object.write_bytes(destination.read_bytes())
        late_archive = out / 'libGopFramebuffer.late.a'
        late_archive.unlink(missing_ok=True)
        subprocess.run(['xcrun', 'ar', 'rcs', late_archive, late_object], check=True)
        import hashlib
        abi_header = source.with_name('OriginalMobileFramebufferABI.h')
        report = {
            'source_sha256': {
                str(source.relative_to(ROOT)): hashlib.sha256(source.read_bytes()).hexdigest(),
                str(abi_header.relative_to(ROOT)): hashlib.sha256(abi_header.read_bytes()).hexdigest(),
            },
            'compiled_object_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
            'late_object_sha256': hashlib.sha256(late_object.read_bytes()).hexdigest(),
            'archive_sha256': hashlib.sha256(late_archive.read_bytes()).hexdigest(),
            'runtime_scope': 'read-only GOP metadata; no panel/GPU/compositor backend',
        }
        (out / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    if args.component == 'ShengUfs':
        # Some older UniXNU scripts look for the legacy native-ufs path. Keep
        # it as a byte-for-byte copy while the kernel link uses sheng-ufs.
        compat = ROOT / 'build/native-ufs'
        compat.mkdir(parents=True, exist_ok=True)
        compat_archive = compat / 'libNativeUfs.a'
        compat_archive.write_bytes(archive.read_bytes())
    print(f'{args.component}: ARM64/iOS 17 archive built')


if __name__ == '__main__':
    main()
