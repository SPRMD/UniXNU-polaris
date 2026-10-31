#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Board recipe for the PolarisHidInput component (drivers/PolarisHidInput/PolarisHidInput.cpp), replacing UniXNU's.

The recipe qualifies the class against the same pinned iPadOS 17.7.11 kernelcache
used by the Polaris stage. The original IOHIDDevice vtable was read once from
that exact prelinked kernel,
after the same checks passed, into scripts/data/hid-device-abi.json; this recipe binds against that table instead.

Output (build/polaris-hid-input): OriginalHidDeviceABI.h, PolarisHidInput.late.o (static constructor removed from
__mod_init_func and exported, so the board probe registers the class after IOHIDFamily has loaded), hid-original-bindings.o
and libPolarisHidInput.a. The Polaris platform link force-loads this archive
only for the iPadOS-stage profile.
"""
import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

BOARD_ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--build-root', type=Path,
                    help='assembled UniXNU tree containing build/xnu and the pinned prelink kit')
args = parser.parse_args()
BUILD_ROOT = args.build_root.resolve() if args.build_root else BOARD_ROOT
OUT = BUILD_ROOT / 'build/polaris-hid-input'
OUT.mkdir(parents=True, exist_ok=True)

# The kit directory name belongs to the pinned upstream tree, which renamed it
# from kits/XnuPrelink to kits/NativePrelink. Resolve it by content so a rename
# fails with the checked paths instead of a bare ModuleNotFoundError.
PREKLINK_KIT_CANDIDATES = ('kits/NativePrelink', 'kits/XnuPrelink')


def prelink_kit(root: Path) -> Path:
    checked = []
    for relative in PREKLINK_KIT_CANDIDATES:
        candidate = root / relative
        checked.append(candidate)
        if ((candidate / 'native_prelink.py').is_file() or
                (candidate / 'native_prelink/__init__.py').is_file()):
            return candidate
    raise SystemExit('PolarisHidInput: no native_prelink kit in ' + str(root) +
                     '; checked ' + ', '.join(str(path) for path in checked))


sys.path.insert(0, str(prelink_kit(BUILD_ROOT)))
from native_prelink import macho


def require(value, why):
    if not value:
        raise SystemExit('PolarisHidInput: ' + why)


def tool(name):
    found = shutil.which(name)
    if found:
        return found
    try:
        prefix = subprocess.check_output(['brew', '--prefix', 'llvm'], text=True).strip()
        candidate = Path(prefix) / 'bin' / name
        if candidate.is_file():
            return str(candidate)
    except (OSError, subprocess.CalledProcessError):
        pass
    for candidate in (f'/opt/homebrew/opt/llvm/bin/{name}', f'/usr/local/opt/llvm/bin/{name}'):
        if Path(candidate).is_file():
            return candidate
    raise SystemExit(f'PolarisHidInput: {name} not found')


abi = json.loads((BOARD_ROOT / 'scripts/data/hid-device-abi.json').read_text())
methods = [int(value, 16) for value in abi['methods']]
require(len(methods) == 207 and abi['instance_bytes'] == 208, 'unexpected recorded IOHIDDevice ABI')
vptr = int(abi['vptr'], 16)

# The same opaque header as UniXNU's recipe: only the slots PolarisHidInput overrides or calls are named.
header = '''// Generated from scripts/data/hid-device-abi.json for the pinned iPadOS 17.7.11 (21H461) kernelcache.
// This is an opaque private ABI shim; do not use with another kernelcache.
#pragma once
#include <IOKit/IOService.h>
#include <IOKit/IOMemoryDescriptor.h>
class IOHIDDevice : public IOService {
 OSDeclareAbstractStructors(IOHIDDevice)
 unsigned char originalPrivate[0xd0-sizeof(IOService)];
public:
 using IOService::setProperty;
 IOReturn Dispatch(IORPC) override;
 void free() override;
 bool init(OSDictionary *properties=nullptr) override;
 bool setProperty(const OSSymbol *,OSObject *) override;
 bool willTerminate(IOService *,IOOptionBits) override;
 IOReturn configureReport(IOReportChannelList *,IOReportConfigureAction,void *,void *) override;
 IOReturn updateReport(IOReportChannelList *,IOReportUpdateAction,void *,void *) override;
 bool start(IOService *) override;
 void stop(IOService *) override;
 bool handleOpen(IOService *,IOOptionBits,void *) override;
 void handleClose(IOService *,IOOptionBits) override;
 bool handleIsOpen(const IOService *) const override;
 bool matchPropertyTable(OSDictionary *,SInt32 *) override;
 IOReturn message(UInt32,IOService *,void *) override;
 IOReturn newUserClient(task_t,void *,UInt32,OSDictionary *,IOUserClient **) override;
'''
for i in range(168, 207):
    if i == 171:
        header += ' virtual OSString *newTransportString() const;\n'
    elif i == 173:
        header += ' virtual OSString *newProductString() const;\n'
    elif i == 180:
        header += ' virtual IOReturn newReportDescriptor(IOMemoryDescriptor **) const=0;\n'
    elif i == 181:
        header += ' virtual IOReturn handleReport(IOMemoryDescriptor *,unsigned,IOOptionBits);\n'
    else:
        header += f' virtual __attribute__((deprecated("Unqualified prototype: never call from source"))) void opaque{i}();\n'
header += '};\nstatic_assert(sizeof(IOHIDDevice)==0xd0,"Original device instance size");\n'
(OUT / 'OriginalHidDeviceABI.h').write_text(header)
source_header = BOARD_ROOT / 'drivers/PolarisHidInput/OriginalHidDeviceABI.h'
if source_header.is_file() and source_header.read_text() != header:
    raise SystemExit('PolarisHidInput: checked-in ABI header differs from generated header')

# Compile with the recorded IOKit flags, as build-arm-driver.py does.
record = json.loads((BUILD_ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json')
                    .read_text().strip().rstrip(','))


def compile_source(source: Path, obj: Path) -> tuple[list[str], int, str]:
    command, index, arguments = [], 0, record['arguments']
    while index < len(arguments):
        value = arguments[index]
        if value == record['file']:
            command.append(str(source))
        elif value == '-o':
            command.extend(['-o', str(obj)])
            index += 1
        elif value == '-Xclang' and index + 1 < len(arguments) and arguments[index + 1].startswith('-W'):
            index += 1
        elif value in ('-MF', '-MJ', '-MT', '-MQ'):
            index += 1
        elif not value.startswith(('-W', '-MF', '-MJ', '-MT', '-MQ')) and value not in ('-MD', '-MMD', '-MP'):
            command.append(value)
        index += 1
    command += ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-c99-designator',
                '-Wno-reorder-init-list', '-Wno-deprecated-enum-enum-conversion',
                '-Wno-unnecessary-virtual-specifier', '-Wno-unknown-warning-option',
                '-Wno-missing-designated-field-initializers', '-Wno-overloaded-virtual',
                '-Wno-deprecated-declarations', '-I', str(OUT), '-I', str(BUILD_ROOT / '.cache/xnu-work/osfmk')]
    result = subprocess.run(command, cwd=record['directory'], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    return command, result.returncode, result.stdout


source = BOARD_ROOT / 'drivers/PolarisHidInput/PolarisHidInput.cpp'
obj = OUT / 'PolarisHidInput.o'
command, returncode, output = compile_source(source, obj)
(OUT / 'compile-command.json').write_text(json.dumps(command, indent=2) + '\n')
(OUT / 'compile.log').write_text(output)
if returncode or not obj.is_file():
    raise SystemExit(output[-4000:])

probe_source = BOARD_ROOT / 'drivers/PolarisHidInput/PolarisHidProbe.cpp'
probe_obj = OUT / 'PolarisHidProbe.o'
probe_command, probe_returncode, probe_output = compile_source(probe_source, probe_obj)
(OUT / 'probe-compile-command.json').write_text(json.dumps(probe_command, indent=2) + '\n')
(OUT / 'probe-compile.log').write_text(probe_output)
if probe_returncode or not probe_obj.is_file():
    raise SystemExit(probe_output[-4000:])

# The compiled vtable: which slots PolarisHidInput owns and which original IOHIDDevice methods it inherits.
raw = obj.read_bytes()
image = macho(raw)
st = next(p for c, p, _ in image['commands'] if c == 2)
sy, count, strings, _ = struct.unpack_from('<4I', raw, st + 8)
symbols = []
for i in range(count):
    ix, kind, section, _, va = struct.unpack_from('<IBBHQ', raw, sy + i * 16)
    symbols.append((raw[strings + ix:raw.index(b'\0', strings + ix)].decode(), va, kind))
vtable = next(va for name, va, _ in symbols if name == '__ZTV15PolarisHidInput')
relocations = {}
for segment in image['segments']:
    for sec in segment['sections']:
        if sec['va'] <= vtable < sec['va'] + sec['size']:
            ro, rc = struct.unpack_from('<2I', raw, sec['command_offset'] + 56)
            for i in range(rc):
                offset, bits = struct.unpack_from('<2I', raw, ro + i * 8)
                if bits >> 27 & 1 and bits >> 28 == 0 and bits >> 25 & 3 == 3:
                    relocations[sec['va'] + offset] = symbols[bits & 0xffffff][0]
compiled = [relocations.get(vtable + 16 + i * 8) for i in range(207)]
require(all(compiled) and vtable + 16 + 207 * 8 not in relocations, 'the compiled vtable is not exactly 207 slots')
bindings = {
    '__ZN11IOHIDDeviceC2EPK11OSMetaClass': int(abi['constructor'], 16),
    '__ZN11IOHIDDeviceD2Ev': int(abi['destructor'], 16),
    '__ZN11IOHIDDevice10gMetaClassE': int(abi['metaclass'], 16),
    '__ZTV11IOHIDDevice': vptr - 16,
}
owned = []
for i, name in enumerate(compiled):
    if name.startswith(('__ZN15PolarisHidInput', '__ZNK15PolarisHidInput')):
        owned.append(i)
    elif '11IOHIDDevice' in name:
        bindings[name] = methods[i]
require(owned == [0, 1, 7, 14, 86, 87, 111, 171, 173, 180], f'unexpected PolarisHidInput overrides {owned}')
undefined = {name for name, _, kind in symbols if kind == 1 and '11IOHIDDevice' in name}
require(undefined <= set(bindings), f'unbound IOHIDDevice imports {sorted(undefined - set(bindings))}')

asm = OUT / 'hid-original-bindings.S'
asm.write_text(''.join(f'.globl {name}\n.set {name}, {address:#x}\n' for name, address in sorted(bindings.items())))
sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-isysroot', sdk, '-c', str(asm), '-o',
                str(OUT / 'hid-original-bindings.o')], check=True)
late = OUT / 'PolarisHidInput.late.o'
subprocess.run([tool('llvm-objcopy'), '--remove-section=__DATA,__mod_init_func',
                '--globalize-symbol=__GLOBAL__sub_I_PolarisHidInput.cpp', str(obj), str(late)], check=True)
archive = OUT / 'libPolarisHidInput.a'
archive.unlink(missing_ok=True)
subprocess.run(['xcrun', 'ar', 'rcs', str(archive), str(late), str(probe_obj),
                str(OUT / 'hid-original-bindings.o')], check=True)
(OUT / 'abi-audit.json').write_text(json.dumps({'owned_slots': owned, 'bindings': {k: hex(v) for k, v in bindings.items()}},
                                               indent=2) + '\n')
print(f'PolarisHidInput: owned slots {owned}, {len(bindings)} original bindings, {archive}')
