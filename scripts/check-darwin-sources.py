#!/usr/bin/env python3
"""Check driver syntax against extracted CI XNU headers without rebuilding XNU.

On Linux/WSL, use a cross clang and an extracted native-buildtree.tgz. This
checks C++ types and warnings, not the Apple linker, prelink ABI or hardware.
It leaves the compiler records and extracted header tree unchanged.
"""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def command_for(record, tree, compiler, source):
    marker = '/build/xnu/ios-obj/'
    original_tree = record['directory'].split(marker, 1)[0]
    arguments = record['arguments']
    command = [str(compiler)]
    index = 1
    while index < len(arguments):
        value = arguments[index]
        if value in ('-o', '-MJ', '-MF', '-MT'):
            index += 2
            continue
        if value == '-Xclang':
            # Apple's vendor switches are unavailable in upstream cross clang.
            index += 2
            continue
        if value == record['file']:
            command.append(str(source))
        elif value not in ('-c', '-fno-c++-static-destructors') and not value.startswith('-W'):
            command.append(value.replace(original_tree, str(tree)))
        index += 1
    command += ['-fsyntax-only', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-parameter', '-Wno-c99-designator',
                '-Wno-reorder-init-list', '-Wno-deprecated-enum-enum-conversion',
                '-Wno-missing-designated-field-initializers',
                '-Wno-unused-but-set-global',
                '-Wno-unnecessary-virtual-specifier',
                '-I', str(tree / '.cache/xnu-work/osfmk'),
                '-I', str(tree / 'build/storage-abi/include'),
                '-I', str(source.parent)]
    return command, Path(record['directory'].replace(original_tree, str(tree)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=ROOT / 'out/darwin-syntax')
    parser.add_argument('sources', nargs='*', type=Path)
    args = parser.parse_args()
    tree = args.tree.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    record = json.loads((tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/'
                         'iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
    sources = args.sources or sorted((ROOT / 'drivers').glob('*/*.cpp'))
    results = []
    for source in sources:
        source = source.resolve()
        command, cwd = command_for(record, tree, args.compiler, source)
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
        label = source.parent.name + '-' + source.stem
        log = args.out / (label + '.log')
        log.write_text(result.stdout + result.stderr)
        results.append({'source': str(source), 'returncode': result.returncode,
                        'log': str(log), 'command': command})
        print(f'{"PASS" if result.returncode == 0 else "FAIL"}: {source}', flush=True)
        if result.returncode:
            print('\n'.join(result.stderr.splitlines()[:20]), flush=True)
    (args.out / 'report.json').write_text(json.dumps({
        'scope': 'syntax-only; not Apple build/link or hardware qualification',
        'tree': str(tree), 'results': results,
    }, indent=2) + '\n')
    return int(any(item['returncode'] for item in results))


if __name__ == '__main__':
    raise SystemExit(main())
