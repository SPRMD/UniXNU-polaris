import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT
SPEC = importlib.util.spec_from_file_location("make_userdata_sparse", PROJECT / "tools" / "make_userdata_sparse.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UserdataSparseTests(unittest.TestCase):
    def test_sparse_wrapper_matches_raw_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "userdata-root.img"
            sparse = root / "userdata-root.simg"
            raw.write_bytes((b"A" * 4096) + (b"\0" * 4096))
            MODULE.convert(raw, sparse)
            facts = MODULE.sparse_facts(sparse)
            self.assertEqual(facts["expanded_bytes"], raw.stat().st_size)
            self.assertEqual(facts["chunk_counts"]["dont_care"], 0)
            self.assertEqual(facts["chunk_counts"]["crc32"], 0)

    def test_report_is_non_flashable_and_consistent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "userdata-root.img"
            sparse = root / "userdata-root.simg"
            report_path = root / "userdata-root.sparse.json"
            raw.write_bytes((b"B" * 4096) + (b"\0" * 4096))
            MODULE.convert(raw, sparse)
            facts = MODULE.sparse_facts(sparse)
            raw_sha = MODULE.sha256_file(raw)
            expanded_sha = MODULE.expand_hash(sparse, facts["total_blocks"])
            report = MODULE.build_report(
                raw, sparse, facts, raw_sha, expanded_sha,
                MODULE.sha256_file(sparse),
            )
            report_path.write_text(json.dumps(report), encoding="utf-8")
            loaded = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(loaded["device_access"])
            self.assertFalse(loaded["flashable"])
            self.assertTrue(loaded["expands_byte_for_byte"])
            self.assertEqual(loaded["raw"]["sha256"], loaded["expanded_sha256"])


if __name__ == "__main__":
    unittest.main()
