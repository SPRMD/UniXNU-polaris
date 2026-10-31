# SPDX-License-Identifier: BSD-2-Clause-Patent
import copy
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('display_abi', ROOT / 'scripts/audit-polaris-display-abi.py')
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


def image(commands=(), payload=b'', cpu=0x100000c, subtype=0):
    uuid = struct.pack('<II', 27, 24) + bytes(16)
    commands = [uuid, *commands]
    return struct.pack('<8I', 0xfeedfacf, cpu, subtype, 2, len(commands),
                       sum(map(len, commands)), 0, 0) + b''.join(commands) + payload


def segment(va=0x1000, fileoff=128, size=32):
    return struct.pack('<II16s4Q4I', 25, 72, b'__TEXT_EXEC', va, size, fileoff, size, 7, 5, 0, 0)


class AuditTests(unittest.TestCase):
    def test_header_rejects_compressed_truncated_and_arm64e(self):
        for bad in (b'IM4P', image()[:-1], image(cpu=7), image(subtype=2)):
            with self.assertRaises(ValueError):
                A.Image(bad)

    def test_command_extents_and_uuid_ambiguity(self):
        for cmd in (struct.pack('<II', 25, 0), struct.pack('<II', 25, 8),
                    struct.pack('<II', 27, 24) + bytes(16)):
            with self.assertRaises(ValueError):
                A.Image(image([cmd]))

    def test_virtual_mapping_bounds(self):
        m = A.Image(image([segment()], bytes(range(32))))
        self.assertEqual(m.read(0x1004, 4), bytes(range(4, 8)))
        for addr, size in ((0xfff, 4), (0x101f, 2), (0x1000, 0), ((1 << 64) - 1, 8)):
            with self.assertRaises(ValueError):
                m.read(addr, size)

    def test_duplicate_mapping_rejected(self):
        m = A.Image(image([segment(fileoff=200), segment(fileoff=200)], bytes(32)))
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            m.read(0x1000, 4)

    def test_symbol_table_bounds(self):
        table = struct.pack('<6I', 2, 24, 0xffffff00, 8, 0, 4)
        m = A.Image(image([table]))
        with self.assertRaisesRegex(ValueError, 'bounds'):
            m.symbols()

    def test_xml_references_and_duplicates(self):
        value = A.prelink_xml(b'<dict><key>a</key><string ID="1">x</string><key>b</key><string IDREF="1"/></dict>\0padding')
        self.assertEqual(value, {'a': 'x', 'b': 'x'})
        for bad in (b'<dict><key>a</key></dict>', b'<string IDREF="missing"/>',
                    b'<dict><key>a</key><true/><key>a</key><false/></dict>'):
            with self.assertRaises(ValueError):
                A.prelink_xml(bad)

    def test_arm64_address_and_call_decode(self):
        self.assertEqual(A.adrp(0xb0ff73a1, 0xfffffff0067866a4), (1, 0xfffffff0055fb000))
        self.assertEqual(A.branch_target(0x94007058, 0xfffffff0067866b8), 0xfffffff0067a2818)
        self.assertEqual(A.branch_target(0x97ffffff, 0x1000), 0xffc)
        self.assertIsNone(A.adrp(0xd65f03c0, 0))
        self.assertIsNone(A.branch_target(0xd65f03c0, 0))
        raw = struct.pack('<8I', 0x90000001, 0x91008021, *([0] * 6))
        self.assertEqual(A.address_pair(A.Image(image([segment()], raw)), 0x1000), (1, 0x1020))

    def test_reference_fails_on_reordered_missing_or_misclassified_slots(self):
        ref = json.loads((ROOT / 'drivers/PolarisDisplayRuntime/abi/sirius-reference.json').read_text())
        self.assertEqual(len(A.validate_reference(ref)['methods']), 358)
        for mutation in ('reorder', 'missing', 'abstract'):
            bad = copy.deepcopy(ref)
            if mutation == 'reorder':
                bad['abi']['methods'].reverse()
            elif mutation == 'missing':
                bad['abi']['methods'].pop()
            else:
                bad['abi']['methods'][0]['abstract'] = True
            with self.assertRaises(ValueError):
                A.validate_reference(bad)

    def test_explicit_path_requires_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                A.resolve_input(Path(tmp) / 'missing')


LOCAL = ROOT.parent.parent / 'inputs/ipsw/kernelcache.release.ipad7.arm64.macho'


@unittest.skipUnless(LOCAL.is_file(), 'local Apple input not distributed with tests')
class LocalEvidenceTests(unittest.TestCase):
    def test_repeatable_report_and_readiness_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'audit.json'
            cmd = [sys.executable, '-B', str(ROOT / 'scripts/audit-polaris-display-abi.py'),
                   '--kernelcache', str(LOCAL), '--output', str(out),
                   '--expect-sha256', 'f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7',
                   '--expect-uuid', 'd6f6e0d2-fe60-38a0-9214-556b7faf8951']
            first = subprocess.run(cmd, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            original = out.read_bytes()
            r = json.loads(original)
            self.assertFalse(r['adapter_ready'])
            self.assertEqual(r['sirius_table']['identical_slots'], 0)
            c = r['legacy_vtable_candidates']
            self.assertEqual(len(c), 1)
            self.assertEqual(c[0]['vptr'], '0xfffffff006f38570')
            self.assertEqual(len(c[0]['slots']), 358)
            self.assertEqual(c[0]['constructor_address_materializations'], ['0xfffffff0067865d8'])
            legacy = r['classes'][0]['constructor_sites'][0]
            self.assertTrue(legacy['verified_metaclass_call'])
            self.assertEqual(legacy['instance_bytes'], 0x18a0)
            self.assertTrue(all(m['stripped'] for m in r['modules'].values()))
            second = subprocess.run(cmd + ['--require-adapter-ready'], capture_output=True)
            self.assertEqual(second.returncode, 2, second.stderr)
            self.assertEqual(out.read_bytes(), original)
            rejected = subprocess.run(cmd + ['--expect-sha256', '0' * 64], capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(out.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
