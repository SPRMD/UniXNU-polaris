import binascii
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BLOCK = 4096
MIB = 1024 * 1024
MANIFEST = 64 * BLOCK


def put(data, offset, fmt, *values):
    struct.pack_into('<' + fmt, data, offset, *values)


def header_crc(data, lba):
    offset = lba * BLOCK
    put(data, offset + 16, 'I', 0)
    put(data, offset + 16, 'I', binascii.crc32(data[offset:offset + 92]))


def tables(data):
    data[2043 * BLOCK:2047 * BLOCK] = data[2 * BLOCK:6 * BLOCK]
    crc = binascii.crc32(data[2 * BLOCK:6 * BLOCK])
    for lba in (1, 2047):
        put(data, lba * BLOCK + 88, 'I', crc)
        header_crc(data, lba)


def manifest_digest(data):
    data[MANIFEST + 4064:MANIFEST + 4096] = hashlib.sha256(data[MANIFEST:MANIFEST + 4064]).digest()


def payload_digest(data, index):
    entry = MANIFEST + 24 + 128 * index
    offset, size = struct.unpack_from('<QQ', data, entry + 32)
    data[entry + 56:entry + 88] = hashlib.sha256(data[MANIFEST + offset:MANIFEST + offset + size]).digest()
    manifest_digest(data)


def image():
    data = bytearray(2048 * BLOCK)
    for lba, other, table in ((1, 2047, 2), (2047, 1, 2043)):
        h = lba * BLOCK
        data[h:h + 8] = b'EFI PART'
        put(data, h + 8, 'IIIIQQQQ', 0x10000, 92, 0, 0, lba, other, 6, 2042)
        data[h + 56:h + 72] = bytes(range(16))
        put(data, h + 72, 'QIII', table, 128, 128, 0)
    for i, (name, first, last) in enumerate((('userdata', 8, 63), ('darwin', 64, 1800))):
        e = 2 * BLOCK + i * 128
        data[e:e + 16] = b'T' * 16
        data[e + 16:e + 32] = bytes([i + 1]) * 16
        put(data, e + 32, 'QQ', first, last)
        encoded = name.encode('utf-16le')
        data[e + 56:e + 56 + len(encoded)] = encoded
    tables(data)
    data[MANIFEST:MANIFEST + 8] = b'SHNGROOT'
    put(data, MANIFEST + 8, 'IIQ', 1, 2, 3 * MIB)
    for i, name in enumerate(('OS', 'SystemOS')):
        e = MANIFEST + 24 + i * 128
        offset = (i + 1) * MIB
        put(data, e, '32sQQII', name.encode(), offset, MIB, 512, 1)
        start = MANIFEST + offset
        data[start:start + MIB] = bytes([0x40 + i]) * MIB
        put(data, start + 24, 'I', 1)
        data[start + 32:start + 36] = b'NXSB'
        put(data, start + 36, 'IQ', BLOCK, MIB // BLOCK)
        data[start + 72:start + 88] = bytes([i + 5]) * 16
        payload_digest(data, i)
    return data


@unittest.skipUnless(shutil.which('clang++'), 'requires WSL/Linux clang++ and libcrypto headers')
class UfsRootLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='polaris-root-test-')
        cls.binary = Path(cls.tmp.name) / 'root-test'
        subprocess.run([shutil.which('clang++'), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-I' + str(ROOT / 'drivers/ShengUfs'),
                        str(ROOT / 'tests/ufs_root_layout_host.cpp'), '-lcrypto', '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self, data, expected=None):
        path = Path(self.tmp.name) / 'lun.img'
        path.write_bytes(data)
        result = subprocess.run([str(self.binary), str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, int(expected is not None), result.stdout + result.stderr)
        if expected:
            self.assertIn(expected, result.stdout)

    def test_valid_image(self):
        self.check(image())

    def test_gpt_rejections(self):
        entry = 2 * BLOCK + 128
        cases = [
            ('primary-crc', BLOCK + 16, 'I', 1, False, 'primary GPT'),
            ('backup-crc', 2047 * BLOCK + 16, 'I', 1, False, 'backup GPT'),
            ('wrong-backup', BLOCK + 32, 'Q', 999, True, 'primary GPT'),
            ('huge-count', BLOCK + 80, 'I', 0xffffffff, True, 'primary GPT'),
            ('array-overflow', BLOCK + 72, 'Q', 0xffffffffffffffff, True, 'primary GPT'),
            ('outside-lun', entry + 40, 'Q', 2048, True, 'partition bounds'),
            ('reversed-range', entry + 40, 'Q', 63, True, 'partition bounds'),
            ('overlap', entry + 32, 'Q', 63, True, 'partition overlap'),
        ]
        for name, offset, fmt, value, repair, reason in cases:
            with self.subTest(name=name):
                data = image(); put(data, offset, fmt, value)
                if repair:
                    tables(data)
                self.check(data, reason)

    def test_duplicate_darwin_and_header_disagreement(self):
        entry = 2 * BLOCK + 128
        data = image()
        src, dest = 2 * BLOCK + 128, 2 * BLOCK + 256
        data[dest:dest + 128] = data[src:src + 128]
        data[dest + 16:dest + 32] = b'Z' * 16
        put(data, dest + 32, 'QQ', 1801, 1900)
        tables(data)
        self.check(data, 'duplicate GPT')
        data = image(); put(data, 2047 * BLOCK + 48, 'Q', 2041)
        header_crc(data, 2047)
        self.check(data, 'headers disagree')
        data = image(); data[src + 56:src + 128] = bytes(72); tables(data)
        self.check(data, 'no canonical darwin')
        for kind in ('name', 'guid', 'array-crc', 'backup-array'):
            with self.subTest(kind=kind):
                data = image()
                if kind == 'name':
                    data[entry + 56:entry + 128] = data[2 * BLOCK + 56:2 * BLOCK + 128]
                    tables(data); reason = 'duplicate GPT'
                elif kind == 'guid':
                    data[entry + 16:entry + 32] = data[2 * BLOCK + 16:2 * BLOCK + 32]
                    tables(data); reason = 'duplicate GPT'
                else:
                    data[(2 if kind == 'array-crc' else 2043) * BLOCK] ^= 1
                    reason = 'array/CRC'
                self.check(data, reason)

    def test_manifest_rejections(self):
        e = MANIFEST + 24
        for offset, fmt, value, reason in [
            (MANIFEST + 12, 'I', 3, 'version/count'),
            (MANIFEST + 16, 'Q', 0xfffffffffffff000, 'image bounds'),
            (e + 32, 'Q', 0xfffffffffffff000, 'window bounds'),
            (e + 40, 'Q', 0xfffffffffffff000, 'window bounds'),
            (e + 40, 'Q', MIB + 512, 'window bounds'),
            (e + 48, 'I', 4096, 'window bounds'),
            (e + 52, 'I', 0, 'window bounds'),
            (e + 128 + 32, 'Q', MIB, 'overlap'),
        ]:
            with self.subTest(offset=offset, value=value):
                data = image(); put(data, offset, fmt, value); manifest_digest(data)
                self.check(data, reason)
        data = image(); data[MANIFEST + 4064] ^= 1
        self.check(data, 'header SHA256')
        data = image(); data[e + 128:e + 160] = data[e:e + 32]; manifest_digest(data)
        self.check(data, 'duplicate/unknown')
        data = image(); data[MANIFEST + 300] = 1; manifest_digest(data)
        self.check(data, 'reserved')

    def test_payload_normalization_and_integrity(self):
        for kind in ('gpt', 'size', 'uuid', 'payload'):
            with self.subTest(kind=kind):
                data = image(); start = MANIFEST + MIB
                if kind == 'gpt':
                    data[start + 32:start + 36] = b'NOPE'
                    data[start + 512:start + 520] = b'EFI PART'
                    payload_digest(data, 0); reason = 'normalized raw'
                elif kind == 'size':
                    put(data, start + 40, 'Q', 0xffffffffffffffff)
                    payload_digest(data, 0); reason = 'normalized raw'
                elif kind == 'uuid':
                    data[start + 72:start + 88] = bytes([6]) * 16
                    payload_digest(data, 0); reason = 'duplicate APFS'
                else:
                    data[start + MIB - 1] ^= 1; reason = 'window SHA256'
                self.check(data, reason)


if __name__ == '__main__':
    unittest.main()
