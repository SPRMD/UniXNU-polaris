import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import unittest
import uuid
import zlib
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stage_gpt', ROOT / 'scripts/build-ios-stage.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


def disk(overlap=False, oversized=False):
    data = bytearray(128 * 512)
    entries = bytearray(4 * 128)
    entries[:16] = uuid.UUID('7C3457EF-0000-11AA-AA11-00306543ECAC').bytes_le
    entries[16:32] = uuid.UUID(int=1).bytes_le
    struct.pack_into('<QQ', entries, 32, 8, 23)
    if overlap:
        entries[128:256] = entries[:128]
        entries[144:160] = uuid.UUID(int=2).bytes_le
    data[1024:1536] = entries
    header = bytearray(512)
    struct.pack_into('<8sIIIIQQQQ16sQIII', header, 0, b'EFI PART', 0x10000,
                     92, 0, 0, 1, 127, 3, 125, uuid.UUID(int=3).bytes_le,
                     2, 4, 128, zlib.crc32(entries))
    struct.pack_into('<I', header, 16, zlib.crc32(header[:92]))
    data[512:1024] = header
    struct.pack_into('<4sIQ', data, 4096 + 32, b'NXSB', 4096, 3 if oversized else 2)
    return data


class GptTests(unittest.TestCase):
    def test_udif_decode_then_gpt_unwrap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'OS.dmg'
            source.write_bytes(b'koly' + bytes(508))
            def extract(script, args):
                self.assertEqual(script, 'udif-extract.py')
                Path(args[1]).write_bytes(disk())
            with patch.object(stage, 'run', side_effect=extract):
                output, geometry = stage.normalize_apfs_input(source, root / 'work')
            self.assertEqual(output.read_bytes()[32:36], b'NXSB')
            self.assertEqual(geometry['container_bytes'], 8192)

    def test_normalizes_partition_without_touching_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'OS.raw'
            original = disk()
            source.write_bytes(original)
            output, geometry = stage.normalize_apfs_input(source, root / 'normalized')
            self.assertEqual(output.read_bytes(), original[4096:12288])
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(geometry['source_partition_offset'], 4096)

    def test_corruption_and_overlapping_partitions_fail(self):
        for position in (528, 1050):
            data = disk()
            data[position] ^= 1
            with self.assertRaises(SystemExit):
                stage.apfs_partition(io.BytesIO(data), len(data))
        data = disk(overlap=True)
        with self.assertRaisesRegex(SystemExit, 'overlapping'):
            stage.apfs_partition(io.BytesIO(data), len(data))

    def test_container_cannot_extend_into_next_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'OS.raw'
            source.write_bytes(disk(oversized=True))
            with self.assertRaisesRegex(SystemExit, 'exceeds'):
                stage.normalize_apfs_input(source, Path(directory) / 'normalized')


if __name__ == '__main__':
    unittest.main()
