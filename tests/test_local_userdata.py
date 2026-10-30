import importlib.util
import tempfile
import unittest
from pathlib import Path


PORT = Path(__file__).resolve().parents[3]
SCRIPT = PORT / "tools" / "build-local-userdata.py"
SPEC = importlib.util.spec_from_file_location("build_local_userdata", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LocalUserdataTests(unittest.TestCase):
    def test_raw_udrw_builds_a_valid_shngroot_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os_image = root / "os.dmg"
            system_image = root / "system.dmg"
            os_image.write_bytes(b"OS" * 1000)
            system_image.write_bytes(b"SYSTEM" * 500)
            board = root / "board.toml"
            board.write_text(
                "[userdata]\nfirst_lba=1\nlast_lba=20000\nlba_bytes=512\n",
                encoding="utf-8",
            )
            output = root / "userdata-root.img"
            report = root / "userdata-root.json"
            MODULE.build(os_image, system_image, output, report, board)
            self.assertEqual(output.read_bytes()[:8], b"SHNGROOT")
            facts = MODULE.shngroot_facts(output)
            self.assertTrue(facts["valid"])
            self.assertTrue(report.is_file())


if __name__ == "__main__":
    unittest.main()
