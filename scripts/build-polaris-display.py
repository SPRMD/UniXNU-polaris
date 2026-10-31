#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Build the standalone GOP CPU runtime from a real Darwin 23 C++ record.

No original Apple addresses, static constructors, prelink, phone access or
configuration changes. Run inside the resolved tree after the bootstrap build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('drivers/GopFramebuffer/PolarisCpuScanout.cpp',
           'drivers/PolarisDisplayRuntime/PolarisDisplayRuntime.cpp')
HEADERS = ('drivers/GopFramebuffer/PolarisCpuScanout.h',
           'drivers/PolarisDisplayRuntime/PolarisDisplayRuntime.h')


def compile_command(record, source, destination):
    args = record['arguments']
    if not args or not record.get('directory') or not record.get('file'):
        raise ValueError('incomplete compiler record')
    command = [args[0]]
    seen_source = 0
    i = 1
    while i < len(args):
        arg = args[i]
        if arg == record['file']:
            seen_source += 1
        elif arg in ('-o', '-MF', '-MT', '-MQ', '-MJ', '-x'):
            if i + 1 == len(args):
                raise ValueError('missing argument for ' + arg)
            i += 1
        elif arg in ('-MD', '-MMD', '-MP', '-MG', '-c'):
            pass
        elif arg.startswith(('-std=', '-stdlib=', '-W')):
            pass
        elif arg.startswith(('-MF', '-MT', '-MQ', '-MJ')):
            pass
        elif arg.startswith('@'):
            raise ValueError('expand response files before recording the compiler command')
        elif arg == '-Xclang' and i + 1 < len(args) and args[i + 1].startswith('-W'):
            i += 1
        else:
            command.append(arg)
        i += 1
    if seen_source != 1:
        raise ValueError('record must contain exactly one matching source argument')
    command += ['-x', 'c++', '-std=c++17', '-fapple-kext', '-nostdinc++',
                '-fno-exceptions', '-fno-rtti', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-parameter', '-Wno-c99-designator',
                '-Wno-reorder-init-list', '-Wno-deprecated-enum-enum-conversion',
                '-Wno-unknown-warning-option', '-c', str(source), '-o', str(destination)]
    return command


def check_object(data):
    if len(data) < 32 or struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 1):
        raise ValueError('expected plain ARM64 Mach-O relocatable object')
    count, size = struct.unpack_from('<II', data, 16)
    end = 32 + size
    if end > len(data):
        raise ValueError('truncated load commands')
    offset, deployment = 32, None
    for _ in range(count):
        if offset + 8 > end:
            raise ValueError('truncated command')
        cmd, length = struct.unpack_from('<II', data, offset)
        if length < 8 or offset + length > end:
            raise ValueError('invalid command length')
        if cmd == 0x32:
            if length < 24:
                raise ValueError('short build version')
            deployment = struct.unpack_from('<II', data, offset + 8)
        if cmd == 0x19:
            if length < 72:
                raise ValueError('short segment')
            sections = struct.unpack_from('<I', data, offset + 64)[0]
            if 72 + sections * 80 > length:
                raise ValueError('short sections')
            for index in range(sections):
                section = offset + 72 + index * 80
                name = data[section:section + 16].split(b'\0')[0]
                flags = struct.unpack_from('<I', data, section + 64)[0]
                if name in (b'__mod_init_func', b'__mod_term_func') or (flags & 255) in (9, 10):
                    raise ValueError('unexpected static constructor/destructor section')
        offset += length
    if offset != end or deployment != (2, 0x110000):
        raise ValueError('expected iOS 17.0 deployment and exact command extent')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--record', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--ar', help='Explicit archive tool; default xcrun ar or llvm-ar')
    args = parser.parse_args()
    root = args.root.resolve()
    recipe = args.record or root / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
    record = json.loads(recipe.read_text().strip().rstrip(','))
    out = (args.out or root / 'build/polaris-display').resolve()
    out.mkdir(parents=True, exist_ok=True)
    archive = out / 'libPolarisDisplayRuntime.a'
    report = out / 'build-report.json'
    # Failed rebuilds must not leave an apparently valid old result.
    archive.unlink(missing_ok=True)
    report.unlink(missing_ok=True)
    objects = []
    commands = []
    for relative in SOURCES:
        source = root / relative
        obj = out / (source.stem + '.o')
        obj.unlink(missing_ok=True)
        command = compile_command(record, source, obj)
        command += ['-I', str(root / '.cache/xnu-work/osfmk')]
        commands.append(command)
        (out / 'compile-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        result = subprocess.run(command, cwd=record['directory'], capture_output=True, text=True)
        (out / (source.stem + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('compile failed: ' + str(source) + '\n' + result.stderr)
        check_object(obj.read_bytes())
        objects.append(obj)
    ar = [args.ar] if args.ar else (['xcrun', 'ar'] if shutil.which('xcrun') else ['llvm-ar'])
    subprocess.run([*ar, 'rcs', str(archive), *map(str, objects)], check=True)
    report.write_text(json.dumps({
        'component': 'PolarisDisplayRuntime', 'kind': 'kernel-cpu-scanout-library',
        'private_apple_bindings': False, 'static_constructors': False,
        'hardware_tested': False, 'compositor_connected': False,
        'record_sha256': digest(recipe), 'archive_sha256': digest(archive),
        'source_sha256': {p: digest(root / p) for p in (*SOURCES, *HEADERS)},
        'objects_sha256': {p.name: digest(p) for p in objects},
    }, indent=2) + '\n')
    print(archive)


if __name__ == '__main__':
    main()
