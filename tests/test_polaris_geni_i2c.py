import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PolarisGeniI2cSourceTests(unittest.TestCase):
    def test_portable_core_and_attribution_are_present(self):
        header = (ROOT / "drivers" / "PolarisGeniI2c" / "PolarisGeniI2c.h").read_text(encoding="utf-8")
        source = (ROOT / "drivers" / "PolarisGeniI2c" / "PolarisGeniI2c.c").read_text(encoding="utf-8")
        readme = (ROOT / "drivers" / "PolarisGeniI2c" / "README.md").read_text(encoding="utf-8")
        self.assertIn("POLARIS_GENI_I2C_H", header)
        self.assertIn("geni_i2c_prepare", source)
        self.assertIn("geni_i2c_timeout", source)
        self.assertIn("BSD-2-Clause-Patent", readme)
        self.assertIn("08cde20edc3254ed6f7df8d0f5384fb887786e8f", readme)

    def test_core_compiles_and_host_model_passes(self):
        compiler = shutil.which("clang") or shutil.which("gcc")
        if compiler is None:
            self.skipTest("no C compiler available")
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "polaris-geni-i2c-host"
            subprocess.run(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                 str(ROOT / "tests" / "polaris_geni_i2c_host.c"),
                 str(ROOT / "drivers" / "PolarisGeniI2c" / "PolarisGeniI2c.c"),
                 "-o", str(exe)], check=True, cwd=ROOT,
            )
            completed = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
            self.assertIn("PASS GENI I2C:", completed.stdout)


if __name__ == "__main__":
    unittest.main()
