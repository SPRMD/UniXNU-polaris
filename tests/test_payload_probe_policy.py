import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "make_payload_esp", ROOT / "scripts" / "make-payload-esp.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PayloadProbePolicyTests(unittest.TestCase):
    def test_board_without_panic_screen_keeps_ordinary_package_unpatched(self):
        self.assertFalse(MODULE.probe_requested({"panic_screen": False}, False, ""))

    def test_panic_screen_or_explicit_extra_enables_probe(self):
        self.assertTrue(MODULE.probe_requested({"panic_screen": True}, False, ""))
        self.assertTrue(
            MODULE.probe_requested({"panic_screen": False}, False, "--reset-after foo")
        )

    def test_no_probe_overrides_both(self):
        self.assertFalse(MODULE.probe_requested({"panic_screen": True}, True, "--reset-after foo"))


if __name__ == "__main__":
    unittest.main()
