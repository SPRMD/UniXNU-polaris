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

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=['ArmDTPlatform', 'ArmCpu', 'ShengUfs', 'PolarisBoardProbe', 'PolarisHardwareServices', 'PolarisPmicInput', 'PolarisPmicRuntime', 'PolarisSynapticsTouch', 'PolarisTransportContracts', 'PolarisA630Probe', 'PolarisRuntime', 'NativeMobileDisplay'])
    args = parser.parse_args()
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
        'PolarisA630Probe': ('polaris-a630-probe', 'PolarisA630Probe', 'PolarisA630Probe'),
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
    command = []
    arguments = record['arguments']
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value == record['file']:
            command.append(str(source))
        elif value == '-o':
            command.extend(['-o', str(destination)])
            index += 1
        elif value == '-Xclang' and arguments[index + 1].startswith('-W'):
            index += 1
        elif not value.startswith('-W'):
            command.append(value)
        index += 1
    command.extend(['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-Wno-c99-designator', '-Wno-reorder-init-list',
                    '-Wno-deprecated-enum-enum-conversion',
                    '-I', str(ROOT / '.cache/xnu-work/osfmk'),
                    '-I', str(source.parent)])
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
    subprocess.run(['xcrun', 'ar', 'rcs', archive, destination], check=True)
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
