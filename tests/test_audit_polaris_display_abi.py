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


COLLECTOR = ROOT / 'drivers/PolarisDisplayRuntime/abi/collect-local-evidence.py'


def load_collector():
    spec = importlib.util.spec_from_file_location('display_evidence', COLLECTOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DecoderTests(unittest.TestCase):
    """The provenance tracer is only trustworthy if its decoders are exact."""

    def setUp(self):
        self.C = load_collector()

    def test_load_store_decodes_known_words(self):
        cases = {
            # word: (kind, size, offset)
            0xf9401800: ('load', 8, 0x30),    # ldr x0,[x0,#0x30]
            0xb9408000: ('load', 4, 0x80),    # ldr w0,[x0,#0x80]
            0xb956b108: ('load', 4, 0x16b0),  # ldr w8,[x8,#0x16b0]
            0xf94ab262: ('load', 8, 0x1560),  # ldr x2,[x19,#0x1560]
            0xf945ca88: ('load', 8, 0xb90),   # ldr x8,[x20,#0xb90]
            0xf905cd09: ('store', 8, 0xb98),  # str x9,[x8,#0xb98]
            0xf90007e0: ('store', 8, 0x8),    # str x0,[sp,#8]
        }
        for word, expected in cases.items():
            got = self.C.decode_load_store(word)
            self.assertIsNotNone(got, hex(word))
            self.assertEqual((got['kind'], got['size'], got['offset']), expected, hex(word))

    def test_load_store_rejects_other_encodings(self):
        for word in (0xd65f03c0, 0xa9037bfd, 0xaa0003f3, 0xd101c3ff, 0x94004893, 0x8b080017):
            self.assertIsNone(self.C.decode_load_store(word), hex(word))

    def test_pair_and_helpers(self):
        pair = self.C.decode_load_store_pair(0xa9035ff8)
        self.assertEqual((pair['load'], pair['offset'], pair['rn']), (0, 0x30, 31))
        self.assertEqual((pair['rt'], pair['rt2']), (24, 23))
        self.assertIsNone(self.C.decode_load_store_pair(0xf9401800))
        self.assertTrue(self.C.is_move_alias(0xaa0003f3))
        self.assertFalse(self.C.is_move_alias(0xaa1403e2 & 0xffffff00))
        self.assertTrue(self.C.is_add_sub_immediate(0xd101c3ff))
        self.assertTrue(self.C.is_conditional_branch(0x34000580))
        self.assertTrue(self.C.is_conditional_branch(0x54000421))
        self.assertFalse(self.C.is_conditional_branch(0xd65f03c0))

    def test_sext(self):
        self.assertEqual(self.C.sext(0x1ff, 9), -1)
        self.assertEqual(self.C.sext(0x0ff, 9), 255)
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


@unittest.skipUnless(LOCAL.is_file(), 'local Apple input not distributed with tests')
class FieldOwnershipTests(unittest.TestCase):
    """Register provenance must attribute each hypothesis offset to an object."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'evidence.json'
            cmd = [sys.executable, '-B', str(COLLECTOR), '--kernelcache', str(LOCAL),
                   '--output', str(out),
                   '--expect-sha256',
                   'f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7',
                   '--expect-uuid', 'd6f6e0d2-fe60-38a0-9214-556b7faf8951']
            done = subprocess.run(cmd, capture_output=True)
            assert done.returncode == 0, done.stderr
            cls.report = json.loads(out.read_text())

    def test_report_never_claims_readiness(self):
        self.assertFalse(self.report['adapter_ready'])
        self.assertTrue(self.report['evidence_completed'])
        self.assertFalse(self.report['generated_private_bindings'])
        self.assertFalse(self.report['hardware_tested'])
        self.assertEqual(self.report['reference_binding_transform']['admitted_bindings'], 0)

    def test_every_hypothesis_offset_is_attributed(self):
        ownership = self.report['swap_lifecycle']['field_ownership']
        self.assertEqual(sorted(ownership),
                         ['0x1560', '0x1568', '0x1570', '0x16b0', '0x16b4', '0xb90', '0xb98'])
        for offset, entry in ownership.items():
            self.assertIn(entry['verdict'],
                          ('proven-this-relative', 'proven-sub-object-of-this',
                           'not-this-relative', 'no-observed-access'), offset)
            self.assertNotEqual(entry['verdict'], 'no-observed-access', offset)
            self.assertGreater(entry['access_count'], 0, offset)

    def test_request_link_offsets_are_list_walk_not_member_access(self):
        # The reference pairs 0xb90/0xb98 with swap-request next/prev links.
        # Locally they are never touched as members of the framebuffer object:
        # they are reached only by walking this->0x1568 and then ->0xb90, which
        # is a list traversal.  That shape is consistent with the reference
        # reading, but it does not prove the runtime class of that object.
        ownership = self.report['swap_lifecycle']['field_ownership']
        for offset in ('0xb90', '0xb98'):
            self.assertEqual(ownership[offset]['verdict'], 'proven-sub-object-of-this', offset)
            self.assertEqual(ownership[offset]['this_relative'], [], offset)
            chains = [row['chain'] for row in ownership[offset]['sub_object']]
            self.assertTrue(chains, offset)
            self.assertTrue(
                all(chain and chain[0] in ('0x1560', '0x1568') for chain in chains),
                (offset, chains))
            # deeper chains must be a forward walk of the link pair
            for chain in chains:
                if len(chain) > 1:
                    self.assertEqual(chain, ['0x1568', '0xb90'], offset)

    def test_request_link_size_arithmetic_is_recorded_not_overclaimed(self):
        summary = self.report['swap_lifecycle']['field_ownership_summary']
        arithmetic = summary['request_link_corroboration']
        self.assertIsNotNone(arithmetic)
        self.assertEqual(arithmetic['request_instance_bytes'], 2976)
        self.assertEqual(arithmetic['link_offsets'], ['0xb90', '0xb98'])
        self.assertEqual(arithmetic['link_spacing'], 8)
        self.assertTrue(arithmetic['links_are_trailing_16_bytes'])
        # The corroboration must not be phrased as proof of the object class.
        # Assert the substance, not one wording: the text has to admit that the
        # runtime class stays unproven while the shape is consistent.
        conclusion = self.report['swap_lifecycle']['field_ownership_summary']['conclusion']
        self.assertIn('hypothesis', conclusion)
        self.assertTrue('not prove' in conclusion or 'no local byte' in conclusion, conclusion)
        self.assertIn('proving', arithmetic['conclusion'])
        self.assertTrue('without proving' in arithmetic['conclusion']
                        or 'not proving' in arithmetic['conclusion'],
                        arithmetic['conclusion'])
        # and the report must never promote it to an admitted binding
        self.assertEqual(self.report['reference_binding_transform']['admitted_bindings'], 0)

    def test_dimension_and_pending_offsets_are_this_relative(self):
        ownership = self.report['swap_lifecycle']['field_ownership']
        for offset in ('0x1560', '0x1568', '0x1570', '0x16b0', '0x16b4'):
            self.assertEqual(ownership[offset]['verdict'], 'proven-this-relative', offset)
            self.assertTrue(ownership[offset]['this_relative'], offset)
        bound = self.report['swap_lifecycle']['field_ownership_summary']['size_bound']
        self.assertTrue(bound['all_offsets_inside_legacy_instance'])
        self.assertEqual(bound['legacy_instance_bytes'], 6304)

    def test_dimension_offsets_are_32_bit_width_height_pair(self):
        # 0x16b0/0x16b4 are read as 4-byte fields from the same object by both
        # the Legacy method and its shipped override.
        ownership = self.report['swap_lifecycle']['field_ownership']
        for offset in ('0x16b0', '0x16b4'):
            sizes = {row['size'] for row in ownership[offset]['this_relative']}
            self.assertEqual(sizes, {4}, offset)
            classes = {row['class_name'] for row in ownership[offset]['this_relative']}
            self.assertEqual(classes, {'IOMobileFramebufferLegacy', 'AppleCLCD-subclass'}, offset)

    def test_no_locking_is_claimed(self):
        locking = self.report['swap_lifecycle']['locking']
        self.assertEqual(locking['methods_with_lock_calls'], [])
        for row in self.report['swap_lifecycle']['register_provenance']:
            if not row.get('traced'):
                continue
            calls = row['shape']['lock_calls']
            self.assertEqual(calls['lock'], calls['unlock'], row['method'])

    def test_iosurface_fields_have_local_writers(self):
        sites = self.report['iosurface_accessors']['field_write_sites']['per_field']
        self.assertEqual(sorted(sites),
                         ['allocation', 'descriptor', 'format', 'height',
                          'planes', 'stride', 'width'])
        for name, row in sites.items():
            self.assertGreater(row['stores'], 0, name)
            self.assertGreater(row['loads'], 0, name)
            self.assertIsNotNone(row['first_store'], name)

    def test_provenance_covers_both_classes(self):
        rows = self.report['swap_lifecycle']['register_provenance']
        traced = [row for row in rows if row.get('traced')]
        self.assertGreater(len(traced), 100)
        classes = {row['class_name'] for row in traced}
        self.assertEqual(classes, {'IOMobileFramebufferLegacy', 'AppleCLCD-subclass'})
        for row in traced:
            self.assertIn('shape', row)
            self.assertTrue(row['shape']['terminated'], row['method'])
            self.assertGreater(row['shape']['instructions'], 0, row['method'])


if __name__ == '__main__':
    unittest.main()
