import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UfsRuntimeHostTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('clang++'), 'requires host clang++ (run in WSL/Linux)')
    def test_production_transport_and_block_adapter(self):
        with tempfile.TemporaryDirectory(prefix='polaris-ufs-') as directory:
            binary = Path(directory) / 'ufs-runtime'
            subprocess.run([
                shutil.which('clang++'), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-function', '-fsanitize=address,undefined',
                '-I' + str(ROOT / 'drivers/ShengUfs'),
                str(ROOT / 'tests/ufs_runtime_host.cpp'), '-o', str(binary),
            ], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
