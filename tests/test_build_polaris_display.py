# SPDX-License-Identifier: BSD-2-Clause-Patent
import importlib.util
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_polaris_display', ROOT / 'scripts/build-polaris-display.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


def object_bytes(commands):
    return struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 1, len(commands),
                       sum(map(len, commands)), 0, 0) + b''.join(commands)


class DisplayBuildTests(unittest.TestCase):
    def test_record_replay_preserves_abi_and_replaces_outputs(self):
        record = {'directory': '/build', 'file': 'old.cpp', 'arguments': [
            'clang++', '-target', 'arm64-apple-ios17.0', '-DPRIVATE', '-Iheaders',
            '-x', 'c++', '-std=gnu++14', '-c', 'old.cpp', '-o', 'old.o',
            '-MJ', 'old.json', '-MFold.d', '-MD', '-Xclang', '-Wold']}
        cmd = BUILD.compile_command(record, Path('/new.cpp'), Path('/new.o'))
        for value in ('old.cpp', 'old.o', 'old.json', '-MFold.d', '-Wold', '-MD'):
            self.assertNotIn(value, cmd)
        self.assertIn('arm64-apple-ios17.0', cmd)
        self.assertIn('-DPRIVATE', cmd)
        self.assertIn('-Iheaders', cmd)
        self.assertEqual(cmd.count(str(Path('/new.cpp'))), 1)
        self.assertEqual(cmd.count('-o'), 1)
        self.assertIn('-fapple-kext', cmd)

    def test_bad_records_fail_closed(self):
        for args in (['clang', 'different.cpp'], ['clang', 'old.cpp', '-o'],
                     ['clang', 'old.cpp', '@flags'], ['clang', 'old.cpp', 'old.cpp']):
            with self.assertRaises(ValueError):
                BUILD.compile_command({'file': 'old.cpp', 'directory': '/', 'arguments': args}, 'x', 'y')

    def test_object_architecture_deployment_and_bounds(self):
        version = struct.pack('<6I', 0x32, 24, 2, 0x110000, 0, 0)
        good = object_bytes([version])
        BUILD.check_object(good)
        cases = [b'', good[:30], good[:-1], object_bytes([]),
                 object_bytes([struct.pack('<6I', 0x32, 24, 1, 0x110000, 0, 0)]),
                 object_bytes([struct.pack('<II', 0x32, 0)])]
        for data in cases:
            with self.assertRaises(ValueError):
                BUILD.check_object(data)

    def test_rejects_static_initializers(self):
        version = struct.pack('<6I', 0x32, 24, 2, 0x110000, 0, 0)
        segment = bytearray(152)
        struct.pack_into('<II', segment, 0, 0x19, 152)
        struct.pack_into('<I', segment, 64, 1)
        segment[72:88] = b'__mod_init_func\0\0'
        with self.assertRaisesRegex(ValueError, 'constructor'):
            BUILD.check_object(object_bytes([version, bytes(segment)]))


if __name__ == '__main__':
    unittest.main()
