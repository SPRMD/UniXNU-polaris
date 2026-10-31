import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BUILD = runpy.run_path(str(ROOT / 'scripts/build-arm-driver.py'))


class LateInitializerTests(unittest.TestCase):
    @unittest.skipUnless(all(shutil.which(x) for x in ('clang++', 'llvm-objcopy', 'llvm-nm')),
                         'requires cross clang and LLVM object tools')
    def test_real_macho_initializer_export_and_automatic_call_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'PolarisHardwareServices.cpp'
            source.write_text('struct Service { Service(); }; Service service;\n')
            obj = root / 'service.o'
            subprocess.run(['clang++', '-target', 'arm64-apple-ios17.0', '-c',
                            str(source), '-o', str(obj)], check=True)
            original = obj.read_bytes()
            self.assertIn(b'__mod_init_func', original)
            try:
                late = BUILD['late_initializer_object'](source, obj)
            except subprocess.CalledProcessError as error:
                # Ubuntu's distro llvm-objcopy is built without Mach-O
                # support. The kernel job still requires the operation; only
                # this host-only capability probe is allowed to skip.
                self.skipTest(f'llvm-objcopy lacks Mach-O support: {error}')
            self.assertEqual(obj.read_bytes(), original)
            self.assertNotIn(b'__mod_init_func', late.read_bytes())
            symbols = subprocess.check_output(['llvm-nm', '-g', str(late)], text=True)
            initializer = next(line.split() for line in symbols.splitlines()
                               if line.endswith('__GLOBAL__sub_I_PolarisHardwareServices.cpp'))
            self.assertEqual(len(initializer), 3)
            self.assertNotEqual(initializer[1], 'U')
            if shutil.which('ld64.lld'):
                caller = root / 'entry.cpp'
                caller.write_text('struct Service { Service(); }; Service::Service() {}\n'
                    'extern "C" void init() __asm__("__GLOBAL__sub_I_PolarisHardwareServices.cpp");\n'
                    'extern "C" void entry() { init(); }\n')
                caller_obj = root / 'entry.o'
                subprocess.run(['clang++', '-target', 'arm64-apple-ios17.0', '-c',
                                str(caller), '-o', str(caller_obj)], check=True)
                subprocess.run(['ld64.lld', '-arch', 'arm64', '-platform_version', 'ios',
                                '17.0', '17.0', '-e', '_entry', '-o', str(root / 'linked'),
                                str(caller_obj), str(late)], check=True, capture_output=True)

    def test_missing_initializer_is_not_silently_accepted(self):
        with patch.dict(BUILD['late_initializer_object'].__globals__,
                        {'llvm_tool': lambda name: name}):
            with patch.object(subprocess, 'run'), patch.object(subprocess, 'check_output', return_value=''):
                with self.assertRaisesRegex(SystemExit, 'not exported'):
                    BUILD['late_initializer_object'](Path('Missing.cpp'), Path('missing.o'))


if __name__ == '__main__':
    unittest.main()
