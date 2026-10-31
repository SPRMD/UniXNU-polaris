#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
# Parser design adapted from UniXNU native_prelink.py. Copyright (c) 2026,
# UniXNU contributors; retained terms: drivers/PolarisDisplayRuntime/abi/SIRIUS-LICENSE.
"""Read-only, offline evidence audit of an ordinary ARM64 prelinked kernelcache.

No private bindings or adapter are emitted. Exit 0 means evidence extraction
succeeded, NOT ABI admission; --require-adapter-ready fails until all semantic
and final-image relocation gates are independently qualified.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
FAMILY = 'com.apple.iokit.IOMobileGraphicsFamily'
SURFACE = 'com.apple.iokit.IOSurface'


def surface_accessors(outer, module):
    # Discover the contiguous simple-property getter block from local code,
    # not by adding a guessed module slide to the Sirius addresses.
    loads = [0xb9408000, 0xb9401000, 0xf9402c00, 0xf9403000,
             0xf9403c00, 0xf9403400, 0x7940e000, 0x3941c800,
             0x3941cc00, 0xb9409800, 0xf9404800, 0xf9404400]
    pattern = b''.join(struct.pack('<II', load, 0xd65f03c0) for load in loads)
    section = module.section('__TEXT_EXEC', '__text')
    raw = outer.read(section['va'], section['size'])
    candidates = [i for i in range(0, len(raw) - len(pattern) + 1, 4) if raw[i:i + len(pattern)] == pattern]
    result = dict(pattern_candidates=len(candidates), leaves=[], runtime_binding_ready=False)
    if len(candidates) != 1:
        return result
    start = candidates[0]
    # Descriptor getter location relative to this unique block is checked by
    # its own exact LDR/RET bytes; semantics taken from the pinned public adapter.
    indices = {'descriptor': -0xdc, 'format': 0, 'width': 16, 'height': 24,
               'stride': 40, 'planes': 72, 'allocation': 80}
    for name, delta in indices.items():
        offset = start + delta
        if offset < 0 or offset + 8 > len(raw):
            return result
        load, ret = struct.unpack_from('<II', raw, offset)
        if ret != 0xd65f03c0 or (name == 'descriptor' and load != 0xf9401800):
            return result
        result['leaves'].append(dict(name=name, address=hex(section['va'] + offset),
            text_offset=hex(offset), load_instruction=hex(load), return_instruction=hex(ret),
            sha256=sha(raw[offset:offset + 8])))
    result.update(text_address=hex(section['va']), text_bytes=section['size'], uuid=module.uuids[0],
                  semantics='pinned Sirius accessor names plus independently matched local load/return instructions; kernel-only stable IOSurface input required',
                  runtime_binding_ready=module.uuids[0] == 'f73d44bb-e674-36e7-a577-83789a86fe7a' and section['size'] == 0x22218)
    return result


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Image:
    # Bounds checking and VM->file translation follow UniXNU native_prelink.py.
    # Embedded kext file offsets are NOT outer kernelcache offsets; all reads
    # of embedded sections below use the outer segments' VM mappings.
    def __init__(self, data, at=0):
        self.data = data
        require(0 <= at <= len(data) - 32, 'truncated Mach-O header')
        magic, cpu, subtype, self.kind, count, size = struct.unpack_from('<6I', data, at)
        require((magic, cpu, subtype) == (0xfeedfacf, 0x100000c, 0), 'expected plain ARM64 Mach-O')
        end = at + 32 + size
        require(end <= len(data), 'load commands outside file')
        self.segments, self.commands, self.uuids = [], [], []
        offset = at + 32
        for _ in range(count):
            require(offset + 8 <= end, 'truncated command')
            cmd, length = struct.unpack_from('<II', data, offset)
            require(length >= 8 and length % 8 == 0 and offset + length <= end, 'invalid command extent')
            self.commands.append((cmd, offset, length))
            if cmd == 27:
                require(length == 24, 'invalid UUID command')
                self.uuids.append(str(uuid.UUID(bytes=data[offset + 8:offset + 24])))
            if cmd == 25:
                require(length >= 72, 'short segment')
                name, va, extent, fileoff, filesize, _, prot, nsects, _ = struct.unpack_from('<16s4Q4I', data, offset + 8)
                require(length == 72 + 80 * nsects and filesize <= extent and va + extent <= 1 << 64, 'invalid segment')
                segment = dict(name=name.rstrip(b'\0').decode(), va=va, size=extent,
                               fileoff=fileoff, filesize=filesize, prot=prot, sections=[])
                for i in range(nsects):
                    n, _, addr, size, _ = struct.unpack_from('<16s16sQQI', data, offset + 72 + i * 80)
                    require(not size or va <= addr <= addr + size <= va + extent, 'section outside segment')
                    segment['sections'].append(dict(name=n.rstrip(b'\0').decode(), va=addr, size=size))
                self.segments.append(segment)
            offset += length
        require(offset == end and len(self.uuids) == 1, 'command extent or UUID ambiguity')

    def offset(self, va, size):
        require(0 <= va < 1 << 64 and 0 < size <= (1 << 64) - va, 'invalid VA range')
        matches = [s['fileoff'] + va - s['va'] for s in self.segments
                   if s['va'] <= va and va + size <= s['va'] + s['filesize']]
        require(len(matches) == 1 and matches[0] + size <= len(self.data), 'unbacked/ambiguous VM range: ' + hex(va))
        return matches[0]

    def read(self, va, size):
        at = self.offset(va, size)
        return self.data[at:at + size]

    def word(self, va):
        return struct.unpack('<I', self.read(va, 4))[0]

    def pointer(self, va):
        return struct.unpack('<Q', self.read(va, 8))[0]

    def section(self, segment, name):
        found = [z for s in self.segments if s['name'] == segment for z in s['sections'] if z['name'] == name]
        require(len(found) == 1, 'missing/ambiguous section ' + segment + ',' + name)
        return found[0]

    def symbols(self):
        tables = [(at, n) for cmd, at, n in self.commands if cmd == 2]
        require(len(tables) == 1 and tables[0][1] == 24, 'symbol table ambiguity')
        symoff, count, stroff, size = struct.unpack_from('<4I', self.data, tables[0][0] + 8)
        require(symoff + count * 16 <= len(self.data) and stroff + size <= len(self.data), 'symbol table out of bounds')
        result = {}
        for i in range(count):
            ix, kind, _, _, value = struct.unpack_from('<IBBHQ', self.data, symoff + i * 16)
            require(ix < size, 'symbol string index out of bounds')
            end = self.data.find(b'\0', stroff + ix, stroff + size)
            require(end >= 0, 'unterminated symbol')
            if kind & 0xe0 or not kind & 1 or not kind & 0x0e:
                continue
            name = self.data[stroff + ix:end].decode()
            result.setdefault(value, []).append(name)
        return count, result


def prelink_xml(blob):
    # Apple's ID/IDREF serialization is not an ordinary plistlib plist.
    refs = {}
    def read(node):
        if 'IDREF' in node.attrib:
            require(node.attrib['IDREF'] in refs, 'unknown XML reference')
            return refs[node.attrib['IDREF']]
        if node.tag == 'dict':
            children = list(node)
            require(len(children) % 2 == 0, 'odd XML dictionary')
            value = {}
            for i in range(0, len(children), 2):
                require(children[i].tag == 'key', 'invalid XML dictionary key')
                key = read(children[i])
                require(key not in value, 'duplicate XML key')
                value[key] = read(children[i + 1])
        elif node.tag == 'array':
            value = [read(n) for n in node]
        elif node.tag in ('string', 'key', 'data'):
            value = node.text or ''
        elif node.tag == 'integer':
            value = int(node.text or '0', 0)
        elif node.tag in ('true', 'false'):
            value = node.tag == 'true'
        else:
            raise ValueError('unsupported XML node ' + node.tag)
        if 'ID' in node.attrib:
            require(node.attrib['ID'] not in refs, 'duplicate XML ID')
            refs[node.attrib['ID']] = value
        return value
    return read(ET.fromstring(blob.split(b'\0', 1)[0]))


def adrp(word, pc):
    if word & 0x9f000000 != 0x90000000:
        return None
    imm = ((word >> 5) & 0x7ffff) * 4 + ((word >> 29) & 3)
    if imm & (1 << 20):
        imm -= 1 << 21
    return word & 31, (pc & ~4095) + imm * 4096


def address_pair(image, pc):
    first = adrp(image.word(pc), pc)
    add = image.word(pc + 4)
    if first and add & 0xffc00000 == 0x91000000 and (add >> 5) & 31 == first[0]:
        return add & 31, first[1] + ((add >> 10) & 4095)
    return None


def branch_target(word, pc):
    if word & 0xfc000000 != 0x94000000:
        return None
    imm = word & 0x3ffffff
    return pc + (imm - (1 << 26) if imm & (1 << 25) else imm) * 4


def resolve_stub(image, target):
    first = adrp(image.word(target), target)
    load, branch = image.word(target + 4), image.word(target + 8)
    if (first and first[0] == 16 and load & 0xffc003ff == 0xf9400210
            and branch == 0xd61f0200):
        return image.pointer(first[1] + ((load >> 10) & 4095) * 8)
    return target


def class_evidence(outer, module, name, symbols):
    strings = module.section('__TEXT', '__cstring')
    raw = outer.read(strings['va'], strings['size'])
    needle = name.encode() + b'\0'
    addresses = []
    start = 0
    while True:
        pos = raw.find(needle, start)
        if pos < 0:
            break
        if pos == 0 or raw[pos - 1] == 0:
            addresses.append(strings['va'] + pos)
        start = pos + len(needle)
    text = module.section('__TEXT_EXEC', '__text')
    sites = []
    for pc in range(text['va'], text['va'] + text['size'] - 24, 4):
        pair = address_pair(outer, pc)
        if not pair or pair[0] != 1 or pair[1] not in addresses:
            continue
        parent = address_pair(outer, pc + 8)
        mov = outer.word(pc + 16)
        target = branch_target(outer.word(pc + 20), pc + 20)
        if not parent or parent[0] != 2 or mov & 0xffe0001f != 0x52800003 or target is None:
            continue
        resolved = resolve_stub(outer, target)
        names = symbols.get(resolved, [])
        sites.append(dict(address=hex(pc), name_address=hex(pair[1]),
                          superclass_metaclass=hex(parent[1]), instance_bytes=(mov >> 5) & 65535,
                          call=hex(target), resolved_call=hex(resolved), symbols=names,
                          verified_metaclass_call='__ZN11OSMetaClassC2EPKcPKS_j' in names,
                          instruction_sha256=sha(outer.read(pc, 24))))
    return dict(name=name, string_addresses=list(map(hex, addresses)), constructor_sites=sites)


def validate_reference(ref):
    abi = ref['abi']
    methods = abi['methods']
    require(len(methods) == 358 and [m['slot'] for m in methods] == list(range(358)), 'reference slots must be ordered and complete')
    abstract = abi['abstract_slots']
    require(len(set(abstract)) == len(abstract) and all(isinstance(i, int) and 0 <= i < 358 for i in abstract), 'bad abstract slots')
    require([m['slot'] for m in methods if m['abstract']] == abstract, 'inconsistent abstract flags')
    return abi


def audit(path, reference):
    data = path.read_bytes()
    outer = Image(data)
    require(outer.kind == 2, 'expected MH_EXECUTE kernelcache')
    abi = validate_reference(reference)
    symbol_count, symbols = outer.symbols()
    info = next(s for s in outer.segments if s['name'] == '__PRELINK_INFO')
    entries = prelink_xml(outer.read(info['va'], info['filesize']))['_PrelinkInfoDictionary']
    require(len({e['CFBundleIdentifier'] for e in entries}) == len(entries), 'duplicate module identifiers')
    modules, summary = {}, {}
    for identifier in (FAMILY, SURFACE):
        entry = next(e for e in entries if e['CFBundleIdentifier'] == identifier)
        address = entry['_PrelinkExecutableLoadAddr']
        sub = Image(data, outer.offset(address, 32))
        require(sub.kind == 11, 'expected MH_KEXT_BUNDLE')
        modules[identifier] = sub
        tables = [(a, n) for c, a, n in sub.commands if c == 2]
        require(len(tables) == 1 and tables[0][1] == 24, 'invalid kext symbol command')
        sym = struct.unpack_from('<4I', data, tables[0][0] + 8)
        summary[identifier] = dict(uuid=sub.uuids[0], version=entry.get('CFBundleVersion'),
            load_address=hex(address), file_offset=hex(outer.offset(address, 32)),
            symbol_table_fields=list(sym), stripped=sym == (0, 0, 0, 0),
            dependencies=entry.get('OSBundleLibraries', {}),
            sections=[dict(segment=s['name'], name=z['name'], address=hex(z['va']), bytes=z['size'],
                           sha256=sha(outer.read(z['va'], z['size'])))
                      for s in sub.segments for z in s['sections'] if z['size'] and s['name'] in ('__TEXT', '__TEXT_EXEC', '__DATA_CONST')])
    family = modules[FAMILY]
    def owner(address):
        for identifier, sub in modules.items():
            for s in sub.segments:
                for z in s['sections']:
                    if z['va'] <= address < z['va'] + z['size']:
                        return identifier + ':' + s['name'] + ',' + z['name']
        for s in outer.segments:
            if s['va'] <= address < s['va'] + s['filesize']:
                return 'kernelcache:' + s['name']
        return 'unmapped'
    classes = [class_evidence(outer, family, n, symbols) for n in
               ('IOMobileFramebufferLegacy', 'IOMobileFramebuffer', 'IOMobileFramebufferService')]
    pure = [a for a, names in symbols.items() if '___cxa_pure_virtual' in names]
    require(len(pure) == 1, 'pure virtual export is ambiguous')
    const = family.section('__DATA_CONST', '__const')
    raw = outer.read(const['va'], const['size'])
    candidates = []
    for pos in range(16, len(raw) - 358 * 8 + 1, 8):
        values = struct.unpack_from('<358Q', raw, pos)
        if [i for i, value in enumerate(values) if value == pure[0]] != abi['abstract_slots']:
            continue
        if raw[pos - 16:pos] != bytes(16):
            continue
        if not all(v % 4 == 0 and ('__text' in owner(v) or owner(v) == 'kernelcache:__TEXT_EXEC') for v in values):
            continue
        vptr = const['va'] + pos
        text = family.section('__TEXT_EXEC', '__text')
        refs = []
        for pc in range(text['va'], text['va'] + text['size'] - 12, 4):
            pair = address_pair(outer, pc)
            if pair and pair[1] == vptr - 16:
                add = outer.word(pc + 8)
                if add == (0x91004000 | (pair[0] << 5) | pair[0]):
                    refs.append(hex(pc))
        rows = [dict(slot=i, address=hex(v), owner=owner(v), symbols=symbols.get(v, []),
                     abstract=v == pure[0], reference_address=abi['methods'][i]['address'],
                     reference_delta=hex(v - int(abi['methods'][i]['address'], 16)),
                     entry_instruction_sha256=sha(outer.read(v, 32))) for i, v in enumerate(values)]
        candidates.append(dict(vptr=hex(vptr), table_prefix_zero=True,
            constructor_address_materializations=refs, slots=rows,
            delta_histogram=dict(Counter(r['reference_delta'] for r in rows)),
            table_sha256=sha(raw[pos:pos + 358 * 8]),
            qualification='candidate: pure-slot fingerprint plus executable entries and constructor references; not method prototypes'))
    reference_vptr = int(abi['legacy_vptr'], 16)
    try:
        actual = struct.unpack('<358Q', outer.read(reference_vptr, 358 * 8))
        matches = sum(v == int(m['address'], 16) for v, m in zip(actual, abi['methods']))
    except ValueError:
        matches = 0
    bindings = []
    for name, address in reference['bindings'].items():
        a = int(address, 16)
        bindings.append(dict(name=name, reference_address=address, local_owner=owner(a),
                             local_symbols=symbols.get(a, []), admitted=False))
    metadata = []
    for name in ('SystemVersion.plist', 'BuildManifest.plist'):
        sibling = path.parent / name
        if sibling.is_file():
            blob = sibling.read_bytes()
            plist = plistlib.loads(blob)
            item = dict(file=name, sha256=sha(blob), product_version=plist.get('ProductVersion'),
                        product_build=plist.get('ProductBuildVersion'),
                        relation='sibling metadata only; decoded Mach-O provenance is not cryptographically established')
            if name == 'BuildManifest.plist':
                item['kernelcache_paths'] = sorted({e.get('Manifest', {}).get('KernelCache', {}).get('Info', {}).get('Path', '')
                                                   for e in plist.get('BuildIdentities', [])})
            metadata.append(item)
    return dict(schema=1, audit_completed=True, adapter_ready=False, sibling_metadata=metadata,
        surface_adapter=surface_accessors(outer, modules[SURFACE]),
        kernelcache=dict(path=str(path.resolve()), bytes=len(data), sha256=sha(data), uuid=outer.uuids[0],
                         architecture='arm64 (not arm64e)', symbol_entries=symbol_count,
                         exported_addresses=len(symbols)),
        relevant_exported_symbols=[dict(address=hex(a), names=names) for a, names in symbols.items()
                                   if any('IOMobileFramebuffer' in n or 'IOSurface' in n for n in names)],
        reference=reference['provenance'], modules=summary, classes=classes,
        sirius_table=dict(vptr=abi['legacy_vptr'], local_owner=owner(reference_vptr),
                          identical_slots=matches, total_slots=358, admissible=False),
        legacy_vtable_candidates=candidates, reference_bindings=bindings,
        missing_evidence=[
            'Stripped kexts: no exported Legacy/IOSurface method names to authenticate per-slot prototypes.',
            'Candidate table is structurally located, but complete parent class graph, method identities and all overridden slot prototypes need instruction-level audit.',
            'IOSurface leaf adapter is implemented with live UUID/instruction validation; trusted loader must supply live text span and producer must supply stable CPU-complete IOSurface.',
            'Swap request offsets, activation/retirement locking, completion and fence ownership require local instruction/control-flow validation.',
            'Final imported-kext relocation map, native-kernel export rebinding and admission order are not supplied by a stock kernelcache.',
            'GOP format, ownership handover and a CPU-complete compositor frame producer remain runtime integration requirements.'],
        generated_private_bindings=False, hardware_tested=False)


def resolve_input(explicit=None):
    if explicit:
        path = Path(explicit).resolve()
        require(path.is_file(), 'kernelcache not found: ' + str(path))
        return path
    relative = Path('inputs/ipsw/kernelcache.release.ipad7.arm64.macho')
    paths = [p.resolve() for p in (ROOT / relative, ROOT.parent.parent / relative) if p.is_file()]
    require(len(paths) == 1, 'missing/ambiguous kernelcache: use --kernelcache explicitly')
    return paths[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernelcache', type=Path)
    parser.add_argument('--reference', type=Path, default=ROOT / 'drivers/PolarisDisplayRuntime/abi/sirius-reference.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expect-sha256')
    parser.add_argument('--expect-uuid')
    parser.add_argument('--require-adapter-ready', action='store_true')
    args = parser.parse_args()
    source = resolve_input(args.kernelcache)
    protected = [source, args.reference.resolve(), source.parent / 'BuildManifest.plist', source.parent / 'SystemVersion.plist']
    require(args.output.resolve() not in protected, 'output must not overwrite an audit input')
    reference_bytes = args.reference.read_bytes()
    report = audit(source, json.loads(reference_bytes))
    report['auditor_sha256'] = sha(Path(__file__).read_bytes())
    report['reference_file_sha256'] = sha(reference_bytes)
    if args.expect_sha256:
        require(report['kernelcache']['sha256'] == args.expect_sha256.lower(), 'kernelcache SHA-256 mismatch')
    if args.expect_uuid:
        require(report['kernelcache']['uuid'] == str(uuid.UUID(args.expect_uuid)), 'kernelcache UUID mismatch')
    # Never leave a stale success marker: output has explicit readiness false.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(dict(output=str(args.output), sha256=report['kernelcache']['sha256'],
                         candidates=len(report['legacy_vtable_candidates']), adapter_ready=report['adapter_ready'])))
    return 2 if args.require_adapter_ready and not report['adapter_ready'] else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, StopIteration, struct.error, ET.ParseError, plistlib.InvalidFileException) as error:
        raise SystemExit('display ABI audit failed: ' + str(error))
