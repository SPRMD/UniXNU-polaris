import bz2
import importlib.util
import io
import os
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
from unittest import mock
import zlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('udif_extract', ROOT / 'scripts/udif-extract.py')
udif = importlib.util.module_from_spec(spec)
spec.loader.exec_module(udif)


def table(first, sectors, runs, base=0):
    header = bytearray(204)
    header[:4] = b'mish'
    struct.pack_into('>IQQQ', header, 4, 1, first, sectors, base)
    struct.pack_into('>I', header, 200, len(runs))
    return bytes(header) + b''.join(struct.pack('>IIQQQQ', *run) for run in runs)


def end(sectors):
    return (udif.TERMINATOR, 0, sectors, 0, 0, 0)


def image(tables, fork=b'', sectors=1, fork_offset=19):
    plist = plistlib.dumps({'resource-fork': {'blkx': [{'Data': t} for t in tables]}})
    trailer = bytearray(512)
    trailer[:4] = b'koly'
    struct.pack_into('>II', trailer, 4, 4, 512)
    struct.pack_into('>QQ', trailer, 24, fork_offset, len(fork))
    struct.pack_into('>II', trailer, 56, 1, 1)
    struct.pack_into('>QQ', trailer, 216, fork_offset + len(fork), len(plist))
    struct.pack_into('>Q', trailer, 492, sectors)
    return bytes(fork_offset) + fork + plist + trailer


class UdifTests(unittest.TestCase):
    def extract(self, raw, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.dmg', Path(directory) / 'out.img'
            source.write_bytes(raw)
            udif.extract(source, output, **kwargs)
            return output.read_bytes()

    def test_binary_plist_data_all_codecs_and_absolute_offsets(self):
        a, b, c = b'A' * 512, b'B' * 512, b'C' * 512
        zipped, bzipped = zlib.compress(b), bz2.compress(c)
        fork = b'base!' + a + zipped + bzipped
        runs = [(udif.RAW, 0, 0, 1, 0, len(a)),
                (udif.COMMENT, 0, 0, 17, 0, 0),
                (udif.ZERO, 0, 1, 1, 0, 0),
                (udif.ZLIB, 0, 2, 1, 512, len(zipped)),
                (udif.BZ2, 0, 3, 1, 512 + len(zipped), len(bzipped)), end(4)]
        # Regions arrive out of order; their starts, not plist order, select output.
        tail = table(4, 1, [(udif.IGNORE, 0, 0, 1, 0, 0), end(1)])
        result = self.extract(image([tail, table(0, 4, runs, base=5)], fork, sectors=5))
        self.assertEqual(result, a + bytes(512) + b + c + bytes(512))

    def test_lzfse_type_seven_and_exact_result(self):
        payload = b'encoded'
        raw = image([table(0, 1, [(0x80000007, 0, 0, 1, 0, len(payload)), end(1)])], payload)
        with mock.patch.object(udif, 'liblzfse') as library:
            library.decompress.return_value = b'X' * 512
            self.assertEqual(self.extract(raw), b'X' * 512)
            library.decompress.assert_called_once_with(payload)
            library.decompress.return_value = b'X' * 513
            with self.assertRaisesRegex(ValueError, 'expected 512'):
                self.extract(raw)

    def test_adc_literals_and_overlapping_two_and_three_byte_references(self):
        self.assertEqual(udif.adc_decompress(b'\x82ABC\x00\x02', 6), b'ABCABC')
        self.assertEqual(udif.adc_decompress(b'\x80x\x40\x00\x00', 5), b'xxxxx')
        self.assertEqual(udif.adc_decompress(b'\x80x\x00\x00', 4), b'xxxx')
        for bad in (b'\x82AB', b'\x00', b'\x40\x00', b'\x00\x00'):
            with self.assertRaises(ValueError):
                udif.adc_decompress(bad, 512)

    def test_adc_full_run_and_missing_lzfse_dependency(self):
        encoded = (b'\xff' + b'x' * 128) * 4
        t = table(0, 1, [(udif.ADC, 0, 0, 1, 0, len(encoded)), end(1)])
        self.assertEqual(self.extract(image([t], encoded)), b'x' * 512)
        with mock.patch.object(udif, 'liblzfse', None):
            with self.assertRaisesRegex(ValueError, 'LZFSE requires'):
                udif.decode(udif.LZFSE, b'encoded', 512)

    def test_adc_run_output_limit(self):
        with self.assertRaises(ValueError):
            udif.decode(udif.ADC, b'\x80x\x00\x00', 3)

    def test_compressed_length_truncation_trailing_and_expansion(self):
        for kind, compress in ((udif.ZLIB, zlib.compress), (udif.BZ2, bz2.compress)):
            for payload in (compress(b'x' * 511), compress(b'x' * 513),
                            compress(b'x' * 512)[:-1], compress(b'x' * 512) + b'junk'):
                with self.subTest(kind=kind, size=len(payload)), self.assertRaises(ValueError):
                    udif.decode(kind, payload, 512)

    def test_invalid_run_and_table_geometry(self):
        good = (udif.RAW, 0, 0, 1, 0, 512)
        cases = [table(0, 1, [good]), table(0, 1, [good, end(0)]),
                 table(0, 1, [(udif.RAW, 0, 1, 1, 0, 512), end(1)]),
                 table(0, 1, [(udif.RAW, 0, 0, 1, 1, 512), end(1)]),
                 table(0, 1, [(udif.RAW, 0, 0, 1, 0, 511), end(1)]),
                 table(0, 1, [(udif.ZERO, 0, 0, 1, 0, 1), end(1)]),
                 table(0, 1, [(0x80000003, 0, 0, 1, 0, 1), end(1)]),
                 table(0, 1, [good, end(1)])[:-1]]
        for t in cases:
            with self.subTest(table=t), self.assertRaises(ValueError):
                udif.read_plan(io.BytesIO(image([t], bytes(512))))

    def test_regions_must_cover_trailer_exactly(self):
        zero = [(udif.ZERO, 0, 0, 1, 0, 0), end(1)]
        for tables, sectors in (([table(0, 1, zero)], 2),
                                ([table(0, 1, zero), table(0, 1, zero)], 1),
                                ([table(1, 1, zero)], 2)):
            with self.assertRaises(ValueError):
                udif.read_plan(io.BytesIO(image(tables, sectors=sectors)))

    def test_plist_string_is_not_double_decoded(self):
        import base64
        text = base64.b64encode(table(0, 1, [end(1)])).decode()
        with self.assertRaisesRegex(ValueError, 'binary mish'):
            udif.read_plan(io.BytesIO(image([text])))

    def test_trailer_bounds_and_segment_refusal(self):
        raw = image([table(0, 1, [(udif.ZERO, 0, 0, 1, 0, 0), end(1)])])
        for at, value, fmt in ((216, len(raw), '>Q'), (224, udif.MAX_PLIST_BYTES + 1, '>Q'),
                               (32, len(raw), '>Q'), (60, 2, '>I'), (492, 0, '>Q')):
            broken = bytearray(raw)
            struct.pack_into(fmt, broken, len(raw) - 512 + at, value)
            with self.assertRaises(ValueError):
                udif.read_plan(io.BytesIO(broken))
        with self.assertRaises(ValueError):
            udif.read_plan(io.BytesIO(b'koly'))

    def test_resource_limit_before_data_read(self):
        length = udif.MAX_DECODED_BYTES // 512 + 1
        t = table(0, length, [(udif.ZLIB, 0, 0, length, 0, 1), end(length)])
        with self.assertRaisesRegex(ValueError, 'resource limits'):
            udif.read_plan(io.BytesIO(image([t], b'x', sectors=length)))

    def test_metadata_reader_does_not_read_data_fork(self):
        fork = b'x' * (2 << 20)
        raw = image([table(0, len(fork)//512, [(udif.RAW, 0, 0, len(fork)//512, 0, len(fork)),
                                             end(len(fork)//512)])], fork, len(fork)//512)
        class Guard(io.BytesIO):
            def read(self, n=-1):
                if n < 0 or n > udif.MAX_PLIST_BYTES:
                    raise AssertionError('unbounded read')
                if 19 <= self.tell() < 19 + len(fork):
                    raise AssertionError('metadata parsing read data fork')
                return super().read(n)
        total, runs = udif.read_plan(Guard(raw))
        self.assertEqual(total, len(fork))
        self.assertEqual(runs[0].stored, len(fork))

    def test_raw_runs_copy_in_bounded_chunks(self):
        data = b'q' * 1536
        t = table(0, 3, [(udif.RAW, 0, 0, 3, 0, len(data)), end(3)])
        with mock.patch.object(udif, 'COPY_BYTES', 127):
            self.assertEqual(self.extract(image([t], data, 3)), data)

    def test_failure_preserves_output_and_removes_partial(self):
        payload = zlib.compress(b'bad-size')
        raw = image([table(0, 1, [(udif.ZLIB, 0, 0, 1, 0, len(payload)), end(1)])], payload)
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory)/'in.dmg', Path(directory)/'out.img'
            source.write_bytes(raw)
            output.write_bytes(b'keep')
            with self.assertRaises(ValueError):
                udif.extract(source, output)
            self.assertEqual(output.read_bytes(), b'keep')
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(list(Path(directory).glob('*.partial')), [])
            with self.assertRaisesRegex(ValueError, 'different'):
                udif.extract(source, source)

    @unittest.skipUnless(os.environ.get('UDIF_TEST_DMG') and os.environ.get('UDIF_TEST_LZFSE'),
                         'set UDIF_TEST_DMG and UDIF_TEST_LZFSE for real IPSW smoke test')
    def test_real_ipsw_first_gpt_and_apfs_runs(self):
        with Path(os.environ['UDIF_TEST_DMG']).open('rb') as handle:
            _, runs = udif.read_plan(handle)
            decoded = []
            for run in runs[:4]:
                self.assertEqual(run.kind, udif.LZFSE)
                decoded.append(udif.decode(run.kind, udif.read_exact(handle, run.offset, run.stored),
                                           run.length, os.environ['UDIF_TEST_LZFSE']))
        self.assertEqual(decoded[0][510:512], b'\x55\xaa')
        self.assertEqual(decoded[1][:8], b'EFI PART')
        self.assertEqual(decoded[3][32:36], b'NXSB')


if __name__ == '__main__':
    unittest.main()
