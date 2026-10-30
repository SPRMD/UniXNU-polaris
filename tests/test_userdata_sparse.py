import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
SPEC = importlib.util.spec_from_file_location("make_userdata_sparse", PROJECT / "tools" / "make_userdata_sparse.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UserdataSparseTests(unittest.TestCase):
    def test_sparse_wrapper_matches_raw_image(self):
        raw = PROJECT / "out" / "polaris" / "userdata" / "userdata-root.img"
        sparse = PROJECT / "out" / "polaris" / "userdata" / "userdata-root.simg"
        self.assertTrue(raw.is_file())
        self.assertTrue(sparse.is_file())
        facts = MODULE.sparse_facts(sparse)
        self.assertEqual(facts["expanded_bytes"], raw.stat().st_size)
        self.assertEqual(facts["chunk_counts"]["dont_care"], 0)
        self.assertEqual(facts["chunk_counts"]["crc32"], 0)

    def test_report_is_non_flashable_and_consistent(self):
        report_path = PROJECT / "out" / "polaris" / "userdata" / "userdata-root.sparse.json"
        self.assertTrue(report_path.is_file())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertFalse(report["device_access"])
        self.assertFalse(report["flashable"])
        self.assertTrue(report["expands_byte_for_byte"])
        self.assertEqual(report["raw"]["sha256"], report["expanded_sha256"])


if __name__ == "__main__":
    unittest.main()
