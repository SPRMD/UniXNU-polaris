#!/usr/bin/env python3
"""Build the pinned IOBlockStorageDevice base class for NativeUfs.

The optional PolarisUfsBlock derives from this class, so its methods must be present at the
source-kernel link. The source and public header are from the same pinned
IOStorageFamily revision prepared by build-platform-kernel.py.
"""
import json
import runpy
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'refer/IOStorageFamily/IOBlockStorageDevice.cpp'
    if not source.is_file():
        raise SystemExit(f'pinned IOStorageFamily source is missing: {source}')
    record_path = (ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/'
                   'iokit/DEVELOPMENT/IOPlatformExpert.cpo.json')
    record = json.loads(record_path.read_text().strip().rstrip(','))
    out = ROOT / 'build/storage-base'
    out.mkdir(parents=True, exist_ok=True)
    obj = out / 'IOBlockStorageDevice.o'
    rewrite = runpy.run_path(str(ROOT / 'scripts/build-arm-driver.py'))['rewrite_compile_command']
    subprocess.run(['python3', str(ROOT / 'scripts/prepare-storage-headers.py')], check=True)
    command = rewrite(record, source, obj)
    command.extend(['-I', str(ROOT / 'build/storage-abi/include'),
                    '-I', str(ROOT / '.cache/xnu-work/osfmk'),
                    '-mgeneral-regs-only'])
    (out / 'compile-command.json').write_text(json.dumps(command, indent=2) + '\n')
    result = subprocess.run(command, cwd=record['directory'], capture_output=True, text=True)
    (out / 'compile.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    data = obj.read_bytes()
    if struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 1):
        raise SystemExit('Expected an ordinary ARM64 Mach-O object')
    archive = out / 'libIOBlockStorageDevice.a'
    archive.unlink(missing_ok=True)
    subprocess.run(['xcrun', 'ar', 'rcs', archive, obj], check=True)
    print(f'IOBlockStorageDevice: ARM64 archive built at {archive}')


if __name__ == '__main__':
    main()
