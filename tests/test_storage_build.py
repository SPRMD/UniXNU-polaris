import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REWRITE = runpy.run_path(str(ROOT / 'scripts/build-arm-driver.py'))['rewrite_compile_command']


class StorageCompileCommandTests(unittest.TestCase):
    def test_warning_pairs_and_forwarded_flags(self):
        record = dict(file='old.cpp', arguments=[
            'clang++', '-Xclang', '-Werror=foo', '-Werror=bar',
            '-Xclang', '-fno-rtti', '-Wp,-DTEST=1', '-Wa,-foo', '-Wl,-bar',
            'old.cpp', '-o', 'old.o'])
        self.assertEqual(REWRITE(record, 'new.cpp', 'new.o'), [
            'clang++', '-Xclang', '-fno-rtti', '-Wp,-DTEST=1', '-Wa,-foo',
            '-Wl,-bar', 'new.cpp', '-o', 'new.o'])

    def test_truncated_pairs_fail_explicitly(self):
        for flag in ('-Xclang', '-o'):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                REWRITE(dict(file='old.cpp', arguments=['clang++', flag]), 'new.cpp', 'new.o')


if __name__ == '__main__':
    unittest.main()
