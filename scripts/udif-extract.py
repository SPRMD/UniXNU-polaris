#!/usr/bin/env python3
"""Stream a single-segment Apple UDIF into a raw disk (not an APFS partition).

Format references: Lekensteyn/dmg2img dmg2img.h and adc.c; UniXNU/UniXNU
scripts/unixnu/udif.py (f0721e9745c45ad2600cd69c74730f1cca55d56a).
https://github.com/Lekensteyn/dmg2img/blob/master/dmg2img.h
https://github.com/Lekensteyn/dmg2img/blob/master/adc.c
https://github.com/UniXNU/UniXNU/blob/f0721e9745c45ad2600cd69c74730f1cca55d56a/scripts/unixnu/udif.py
plistlib already decodes <data>. mish has a 204-byte header and 40-byte runs.
This checks geometry and decoded lengths, not UDIF checksums or signatures.

  udif-extract.py input.dmg output.img [--lzfse-bin /path/to/lzfse]
"""
import argparse
import bz2
import os
from pathlib import Path
import plistlib
import struct
import subprocess
import tempfile
from typing import NamedTuple
import zlib

try:
    import liblzfse
except ImportError:
    try:
        import lzfse as liblzfse
    except ImportError:
        liblzfse = None

ZERO, RAW, IGNORE = 0, 1, 2
ADC, ZLIB, BZ2, LZFSE = 0x80000004, 0x80000005, 0x80000006, 0x80000007
COMMENT, TERMINATOR = 0x7FFFFFFE, 0xFFFFFFFF
SECTOR = 512
COPY_BYTES = 1 << 20
MAX_PLIST_BYTES = 32 << 20
MAX_COMPRESSED_BYTES = 128 << 20
MAX_DECODED_BYTES = 256 << 20
MAX_IMAGE_BYTES = 1 << 40


class Run(NamedTuple):
    kind: int
    target: int
    length: int
    offset: int
    stored: int


def read_exact(handle, offset, length):
    handle.seek(offset)
    data = handle.read(length)
    if len(data) != length:
        raise ValueError(f'short read at {offset}: {len(data)} of {length}')
    return data


def bounded(offset, length, limit, label):
    if offset < 0 or length < 0 or offset > limit or length > limit - offset:
        raise ValueError(f'{label} outside bounds')


def read_plan(handle):
    """Validate all metadata before creating output; do not read the data fork."""
    size = handle.seek(0, 2)
    if size < 512:
        raise ValueError('short UDIF trailer')
    trailer = read_exact(handle, size - 512, 512)
    if trailer[:4] != b'koly' or struct.unpack_from('>II', trailer, 4) != (4, 512):
        raise ValueError('expected version-4, 512-byte koly trailer')
    if struct.unpack_from('>II', trailer, 56) != (1, 1):
        raise ValueError('segmented UDIF is not supported')
    fork, fork_size = struct.unpack_from('>QQ', trailer, 24)
    xml, xml_size = struct.unpack_from('>QQ', trailer, 216)
    total = struct.unpack_from('>Q', trailer, 492)[0] * SECTOR
    if not 0 < total <= MAX_IMAGE_BYTES:
        raise ValueError('invalid or excessive raw image size')
    bounded(fork, fork_size, size - 512, 'data fork')
    bounded(xml, xml_size, size - 512, 'plist')
    if not 0 < xml_size <= MAX_PLIST_BYTES:
        raise ValueError('invalid or excessive plist size')
    if fork_size and max(fork, xml) < min(fork + fork_size, xml + xml_size):
        raise ValueError('plist overlaps data fork')
    try:
        blocks = plistlib.loads(read_exact(handle, xml, xml_size))['resource-fork']['blkx']
    except (ValueError, KeyError, TypeError, plistlib.InvalidFileException) as error:
        raise ValueError(f'invalid UDIF resource plist: {error}') from error
    if not isinstance(blocks, list) or not blocks:
        raise ValueError('missing blkx regions')
    runs, regions = [], []
    for block in blocks:
        mish = block.get('Data') if isinstance(block, dict) else None
        if not isinstance(mish, bytes) or len(mish) < 204 or mish[:4] != b'mish':
            raise ValueError('blkx Data must be a binary mish table')
        if struct.unpack_from('>I', mish, 4)[0] != 1:
            raise ValueError('unsupported mish version')
        first, sectors, base = struct.unpack_from('>QQQ', mish, 8)
        count = struct.unpack_from('>I', mish, 200)[0]
        if not sectors or not count or len(mish) != 204 + count * 40:
            raise ValueError('invalid mish size/run count')
        bounded(first * SECTOR, sectors * SECTOR, total, 'region')
        bounded(base, 0, fork_size, 'mish DataStart')
        regions.append((first, sectors))
        cursor = 0
        ended = False
        for index in range(count):
            kind, _, start, length, offset, stored = struct.unpack_from('>IIQQQQ', mish, 204 + 40 * index)
            if kind == TERMINATOR:
                if index != count - 1 or start != sectors or length or stored:
                    raise ValueError('invalid mish terminator')
                ended = True
                continue
            if kind == COMMENT:
                continue  # An annotation is not a zero-filled extent.
            if start != cursor or not length or start + length > sectors:
                raise ValueError('gap, overlap or out-of-bounds mish run')
            cursor += length
            decoded = length * SECTOR
            if kind not in (ZERO, IGNORE, RAW, ADC, ZLIB, BZ2, LZFSE):
                raise ValueError(f'unsupported block type {kind:#x}')
            bounded(base + offset, stored, fork_size, 'run in data fork')
            if kind in (ZERO, IGNORE):
                if stored:
                    raise ValueError('zero/ignore run has stored bytes')
            elif kind == RAW:
                if stored != decoded:
                    raise ValueError('raw run length mismatch')
            elif not 0 < stored <= MAX_COMPRESSED_BYTES or decoded > MAX_DECODED_BYTES:
                raise ValueError('compressed run exceeds resource limits')
            runs.append(Run(kind, (first + start) * SECTOR, decoded, fork + base + offset, stored))
        if not ended or cursor != sectors:
            raise ValueError('incomplete mish region')
    cursor = 0
    for first, sectors in sorted(regions):
        if first != cursor:
            raise ValueError('gap or overlap between blkx regions')
        cursor += sectors
    if cursor * SECTOR != total:
        raise ValueError('blkx regions do not cover trailer sector count')
    return total, sorted(runs, key=lambda run: run.target)


def adc_decompress(data, expected):
    out = bytearray()
    pos = 0
    while pos < len(data):
        tag = data[pos]
        pos += 1
        if tag & 0x80:
            length = (tag & 0x7f) + 1
            if pos + length > len(data) or len(out) + length > expected:
                raise ValueError('short or excessive ADC literal')
            out.extend(data[pos:pos + length])
            pos += length
        else:
            width = 2 if tag & 0x40 else 1
            length = (tag & 0x3f) + 4 if width == 2 else ((tag & 0x3f) >> 2) + 3
            if pos + width > len(data) or len(out) + length > expected:
                raise ValueError('short or excessive ADC back-reference')
            offset = int.from_bytes(data[pos:pos + width], 'big')
            if width == 1:
                offset |= (tag & 3) << 8
            pos += width
            distance = offset + 1
            if distance > len(out):
                raise ValueError('ADC back-reference precedes output')
            for _ in range(length):
                out.append(out[-distance])
    return bytes(out)


def external_lzfse(chunk, expected, executable):
    # The reference tool accepts a file. Avoid capturing unbounded stdout.
    with tempfile.TemporaryDirectory(prefix='udif-lzfse-') as directory:
        encoded = Path(directory) / 'run.lzfse'
        encoded.write_bytes(chunk)
        with subprocess.Popen([str(executable), '-decode', '-i', str(encoded)],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as child:
            try:
                data = child.stdout.read(expected + 1)
                if len(data) > expected:
                    raise ValueError('LZFSE output exceeds run length')
                status = child.wait(timeout=60)
                if status:
                    raise ValueError(f'LZFSE decoder failed ({status})')
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
    return data


def decode(kind, chunk, expected, lzfse_bin=None):
    if not 0 < expected <= MAX_DECODED_BYTES or len(chunk) > MAX_COMPRESSED_BYTES:
        raise ValueError('compressed run exceeds resource limits')
    if kind == ZLIB:
        decoder = zlib.decompressobj()
        plain = decoder.decompress(chunk, expected + 1)
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('incomplete, oversized or trailing zlib stream')
    elif kind == BZ2:
        decoder = bz2.BZ2Decompressor()
        plain = decoder.decompress(chunk, max_length=expected + 1)
        if not decoder.eof or decoder.unused_data:
            raise ValueError('incomplete, oversized or trailing bzip2 stream')
    elif kind == ADC:
        plain = adc_decompress(chunk, expected)
    elif kind == LZFSE:
        if lzfse_bin:
            plain = external_lzfse(chunk, expected, lzfse_bin)
        elif liblzfse is not None:
            plain = liblzfse.decompress(chunk)
        else:
            raise ValueError('LZFSE requires liblzfse/lzfse Python module or --lzfse-bin')
    else:
        raise ValueError(f'unsupported compressed type {kind:#x}')
    if len(plain) != expected:
        raise ValueError(f'block {kind:#x} decoded {len(plain)} bytes, expected {expected}')
    return plain


def extract(source, output, lzfse_bin=None):
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve() or (output.exists() and os.path.samefile(source, output)):
        raise ValueError('input and output must be different files')
    partial = None
    try:
        with source.open('rb') as handle:
            total, runs = read_plan(handle)
            print(f'{source}: {total} raw bytes, {len(runs)} runs', flush=True)
            with tempfile.NamedTemporaryFile(mode='w+b', prefix=output.name + '.', suffix='.partial',
                                             dir=output.parent, delete=False) as target:
                partial = Path(target.name)
                target.truncate(total)
                for run in runs:
                    if run.kind in (ZERO, IGNORE):
                        continue  # Newly created sparse ranges read as zero.
                    target.seek(run.target)
                    if run.kind == RAW:
                        handle.seek(run.offset)
                        remaining = run.stored
                        while remaining:
                            chunk = handle.read(min(COPY_BYTES, remaining))
                            if not chunk:
                                raise ValueError('short raw run')
                            target.write(chunk)
                            remaining -= len(chunk)
                    else:
                        chunk = read_exact(handle, run.offset, run.stored)
                        target.write(decode(run.kind, chunk, run.length, lzfse_bin))
            os.replace(partial, output)
            partial = None
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)
    print(f'done: {output} ({total} bytes; checksums/signatures not verified)', flush=True)
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dmg', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--lzfse-bin', type=Path, help="Apple's reference lzfse decoder")
    args = parser.parse_args()
    try:
        extract(args.dmg, args.out, args.lzfse_bin)
    except (OSError, ValueError, EOFError, zlib.error, subprocess.SubprocessError) as error:
        parser.exit(1, f'UDIF: {error}\n')


if __name__ == '__main__':
    main()
