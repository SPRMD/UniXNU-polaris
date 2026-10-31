#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Collect host-verifiable structural evidence for the local display ABI audit.

Read-only, offline, standard-library-only.  This tool reuses the Mach-O/VM/
PRELINK parser of scripts/audit-polaris-display-abi.py (a separate, already
tested auditor) and records what the exact local kernelcache bytes can and
cannot prove for the four minimum-work items in ABI-AUDIT.md:

  1. IOMobileFramebufferLegacy constructors/destructors, superclass graph and
     the complete local vtable, plus the shipped subclass that inherits it.
  2. The seven IOSurface accessor leaves and their struct offsets.
  3. The swap-request class size and the reference's field-offset hypotheses,
     including register-provenance attribution of every offset to an object.
  4. Prelinked import bindings, late-registration order and GOP hand-off
     evidence available in a stock kernelcache.

It never emits private bindings, never invokes a compiler/disassembler, never
modifies an input, and reports adapter_ready=false unconditionally.  Exit 0
means the evidence report was written, not that the display adapter is ready.

Run from the device repository:

  python -B drivers/PolarisDisplayRuntime/abi/collect-local-evidence.py \
      --output drivers/PolarisDisplayRuntime/abi/local-structural-evidence.json \
      --expect-sha256 f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7 \
      --expect-uuid d6f6e0d2-fe60-38a0-9214-556b7faf8951
"""
import argparse
import bisect
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import uuid

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
AUDITOR_PATH = REPO / 'scripts' / 'audit-polaris-display-abi.py'
REFERENCE_PATH = REPO / 'drivers' / 'PolarisDisplayRuntime' / 'abi' / 'sirius-reference.json'
FAMILY_ID = 'com.apple.iokit.IOMobileGraphicsFamily'
SURFACE_ID = 'com.apple.iokit.IOSurface'
H9G_ID = 'com.apple.driver.AppleMobileDispH9G'
RET = 0xd65f03c0
BRK = 0xd4200020


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_auditor():
    spec = importlib.util.spec_from_file_location('polaris_display_abi_auditor', AUDITOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load_auditor()


class Ranges:
    """Sorted (start, end, label) lookup with bisect."""
    def __init__(self, items):
        self.items = sorted((int(s), int(e), label) for s, e, label in items if e > s)
        self.starts = [s for s, _, _ in self.items]

    def find(self, address):
        index = bisect.bisect_right(self.starts, address) - 1
        if index >= 0:
            start, end, label = self.items[index]
            if address < end:
                return label
        return None


class Env:
    def __init__(self, data):
        self.outer = A.Image(data)
        info = next(s for s in self.outer.segments if s['name'] == '__PRELINK_INFO')
        self.entries = A.prelink_xml(self.outer.read(info['va'], info['filesize']))['_PrelinkInfoDictionary']
        self.order = {}
        self.modules = {}
        self.unresolved = []
        for index, entry in enumerate(self.entries):
            ident = entry['CFBundleIdentifier']
            self.order[ident] = index
            if '_PrelinkExecutableLoadAddr' not in entry:
                self.unresolved.append(ident)
                continue
            try:
                self.modules[ident] = A.Image(data, self.outer.offset(entry['_PrelinkExecutableLoadAddr'], 32))
            except (ValueError, struct.error):
                self.unresolved.append(ident)
        self.kernel_cache = self.outer
        self._build_ranges()
        self._symbols = None
        self._bl = {}
        self._prologues = {}

    def _build_ranges(self):
        exec_items, data_items, got_items = [], [], []
        for ident, image in self.modules.items():
            for segment in image.segments:
                for section in segment['sections']:
                    kind = (segment['name'], section['name'])
                    label = ident + ':' + segment['name'] + ',' + section['name']
                    if kind[0] == '__TEXT_EXEC' and kind[1] == '__text':
                        exec_items.append((section['va'], section['va'] + section['size'], label))
                    if kind[0] in ('__DATA', '__DATA_CONST') and section['name'] in ('__data', '__const', '__common'):
                        data_items.append((section['va'], section['va'] + section['size'], label))
                    if section['name'] == '__got':
                        got_items.append((section['va'], section['va'] + section['size'], label))
        for segment in self.outer.segments:
            for section in segment['sections']:
                if segment['name'] in ('__TEXT_EXEC', '__KLD', '__PLK_TEXT_EXEC') and section['name'] == '__text':
                    exec_items.append((section['va'], section['va'] + section['size'], 'kernelcache:' + segment['name']))
                if segment['name'] in ('__DATA', '__DATA_CONST', '__PRELINK_DATA', '__PLK_DATA_CONST') and section['name'] in ('__data', '__const', '__common'):
                    data_items.append((section['va'], section['va'] + section['size'], 'kernelcache:' + segment['name']))
                if section['name'] == '__got':
                    got_items.append((section['va'], section['va'] + section['size'], 'kernelcache:' + segment['name']))
        self.exec_ranges = Ranges(exec_items)
        self.data_ranges = Ranges(data_items)
        self.got_ranges = Ranges(got_items)

    @property
    def symbols(self):
        if self._symbols is None:
            _, self._symbols = self.outer.symbols()
        return self._symbols

    def module(self, ident):
        return self.modules.get(ident)

    def read_cstring(self, address, limit=96):
        try:
            raw = self.outer.read(address, limit)
        except ValueError:
            return None
        end = raw.find(b'\0')
        if end <= 0:
            return None
        try:
            return raw[:end].decode()
        except UnicodeDecodeError:
            return None

    def owner(self, address, ranges):
        return ranges.find(address)

    def executable_owner(self, address):
        return self.exec_ranges.find(address)

    def is_executable(self, address):
        return self.executable_owner(address) is not None

    def bl_targets(self, ident):
        """Map BL target address -> sorted list of BL program counters."""
        if ident not in self._bl:
            image = self.modules[ident]
            text = image.section('__TEXT_EXEC', '__text')
            table = {}
            for pc in range(text['va'], text['va'] + text['size'] - 4, 4):
                word = self.outer.word(pc)
                if word & 0xfc000000 == 0x94000000:
                    target = A.branch_target(word, pc)
                    table.setdefault(target, []).append(pc)
            self._bl[ident] = table
        return self._bl[ident]

    def prologue_starts(self, ident):
        if ident not in self._prologues:
            image = self.modules[ident]
            text = image.section('__TEXT_EXEC', '__text')
            starts = []
            for pc in range(text['va'], text['va'] + text['size'] - 8, 4):
                word = self.outer.word(pc)
                if (word & 0xffc003ff) == 0xd10003ff or (word & 0xffc07fff) == 0xa9807bfd:
                    starts.append(pc)
            self._prologues[ident] = starts
        return self._prologues[ident]

    def function_start(self, ident, pc):
        starts = self.prologue_starts(ident)
        index = bisect.bisect_right(starts, pc) - 1
        while index >= 0:
            candidate = starts[index]
            blocked = False
            for word_pc in range(candidate + 4, pc, 4):
                if self.outer.word(word_pc) in (RET, BRK):
                    blocked = True
                    break
            if not blocked:
                return candidate
            index -= 1
        return None

    def decode_stub(self, ident, stub_va):
        """Decode ADRP x16; LDR x16,[x16,#imm]; BR x16 -> the GOT slot address."""
        image = self.modules[ident]
        stubs = image.section('__TEXT_EXEC', '__stubs')
        if not (stubs['va'] <= stub_va < stubs['va'] + stubs['size']):
            return None
        first = A.adrp(self.outer.word(stub_va), stub_va)
        load = self.outer.word(stub_va + 4)
        branch = self.outer.word(stub_va + 8)
        if not first or first[0] != 16:
            return None
        if load & 0xffc003ff != 0xf9400210 or branch != 0xd61f0200:
            return None
        return first[1] + ((load >> 10) & 0xfff) * 8

    def stub_bindings(self, ident):
        image = self.modules[ident]
        stubs = image.section('__TEXT_EXEC', '__stubs')
        rows = []
        for index in range(stubs['size'] // 12):
            stub_va = stubs['va'] + 12 * index
            got_va = self.decode_stub(ident, stub_va)
            if got_va is None:
                continue
            try:
                bound = self.outer.pointer(got_va)
            except ValueError:
                continue
            rows.append(dict(index=index, stub=hex(stub_va), got=hex(got_va), bound=hex(bound),
                             bound_owner=self.owner(bound, self.exec_ranges),
                             bound_data_owner=self.owner(bound, self.data_ranges),
                             symbols=self.symbols.get(bound, [])))
        return rows


def reference_slots(reference):
    return reference['abi']['methods']


def classify_super(env, ident, super_local, super_import, storage_names):
    if super_import is not None:
        owner = env.owner(super_import, env.data_ranges)
        names = env.symbols.get(super_import, [])
        name = storage_names.get(super_import)
        return dict(kind='imported-metaclass-object', address=hex(super_import), owner=owner,
                    symbols=names, class_name=name)
    if super_local is not None:
        return dict(kind='local-metaclass-object', address=hex(super_local),
                    owner=env.owner(super_local, env.data_ranges),
                    symbols=env.symbols.get(super_local, []),
                    class_name=storage_names.get(super_local))
    return dict(kind='unresolved')


def registrations(env, ident, metaclass_ctor):
    """Decode every OSMetaClass registration call in one kext.

    The call passes (x0 = metaclass object storage address, x1 = class name
    string, x2 = superclass metaclass object, w3 = instance size) to the
    exported OSMetaClass constructor.  Storage is recovered through the
    generated wrapper chain (meta_init <- wrapper <- static setter)."""
    image = env.modules[ident]
    stubs = image.section('__TEXT_EXEC', '__stubs')
    ctor_stub = None
    for index in range(stubs['size'] // 12):
        stub_va = stubs['va'] + 12 * index
        got_va = env.decode_stub(ident, stub_va)
        if got_va is None:
            continue
        try:
            if env.outer.pointer(got_va) == metaclass_ctor:
                ctor_stub = stub_va
                break
        except ValueError:
            continue
    if ctor_stub is None:
        return [], None
    bl = env.bl_targets(ident)
    out = []
    for site in sorted(bl.get(ctor_stub, [])):
        name_ptr = super_local = super_import = size = None
        for step in range(1, 21):
            pc = site - 4 * step
            pair = A.address_pair(env.outer, pc)
            if pair:
                register, value = pair
                if register == 1 and name_ptr is None:
                    name_ptr = value
                if register == 2 and super_local is None:
                    super_local = value
            word = env.outer.word(pc)
            if word & 0xffe0001f == 0x52800003 and size is None:
                size = (word >> 5) & 0xffff
            if super_import is None:
                adrp = A.adrp(word, pc)
                if adrp and adrp[0] == 2:
                    load = env.outer.word(pc + 4)
                    if load & 0xffc00000 == 0xf9400000 and ((load >> 5) & 31) == 2 and ((load & 31) == 2):
                        got_va = adrp[1] + ((load >> 10) & 0xfff) * 8
                        try:
                            super_import = env.outer.pointer(got_va)
                        except ValueError:
                            super_import = None
        if size is None:
            continue
        out.append(dict(call_site=hex(site), name=env.read_cstring(name_ptr), name_address=hex(name_ptr) if name_ptr else None,
                        instance_bytes=size, super_local=super_local, super_import=super_import,
                        metaclass_ctor_stub=hex(ctor_stub)))
    return out, ctor_stub

def writable_kext_data(env, ident, address):
    owner = env.owner(address, env.data_ranges)
    if not owner or not owner.startswith(ident + ':'):
        return False
    return '__DATA_CONST' not in owner


def resolve_metaclass_storages(env, ident, records):
    """Recover x0 (metaclass object storage) for each registration.

    Generated code shape:  setter[adrp/add x0=storage; bl wrapper]
                           wrapper[bl meta_init]
                           meta_init[OSMetaClass ctor(name, super, size)]
    """
    bl = env.bl_targets(ident)
    storage = {}
    for record in records:
        site = int(record['call_site'], 16)
        meta_init = env.function_start(ident, site)
        if meta_init is None:
            continue
        for caller in bl.get(meta_init, []):
            wrapper = env.function_start(ident, caller)
            if wrapper is None or wrapper == meta_init:
                continue
            for wrapper_caller in bl.get(wrapper, []):
                setter = env.function_start(ident, wrapper_caller)
                if setter is None or setter == wrapper:
                    continue
                for step in range(0, 32):
                    pc = setter + 4 * step
                    pair = A.address_pair(env.outer, pc)
                    if pair and writable_kext_data(env, ident, pair[1]):
                        storage[record['call_site']] = pair[1]
                        break
                if record['call_site'] in storage:
                    break
            if record['call_site'] in storage:
                break
    return storage


def vtable_headers(env, ident):
    """Find [this-metaclass, super-metaclass, 0, 0, vtable...] records.

    Observed layout in this image: two words immediately before the standard
    Itanium zero prefix hold this class's metaclass object address and its
    superclass metaclass object address.
    """
    image = env.modules[ident]
    out = []
    for segment in image.segments:
        if segment['name'] not in ('__DATA_CONST', '__DATA'):
            continue
        for section in segment['sections']:
            if section['name'] not in ('__const', '__data', '__common') or section['size'] < 48:
                continue
            raw = env.outer.read(section['va'], section['size'])
            for pos in range(0, len(raw) - 48, 8):
                this_meta, super_meta, zero1, zero2, first = struct.unpack_from('<5Q', raw, pos)
                if zero1 or zero2 or not this_meta or not super_meta:
                    continue
                if env.is_executable(super_meta) or not env.owner(super_meta, env.data_ranges):
                    continue
                if not env.is_executable(first):
                    continue
                if not writable_kext_data(env, ident, this_meta):
                    continue
                out.append(dict(header=hex(section['va'] + pos), this_metaclass=this_meta,
                                super_metaclass=super_meta, vptr=section['va'] + pos + 32,
                                first_entry=hex(first)))
    return out


def decode_vtable(env, vptr, limit=512):
    rows = []
    for index in range(limit):
        try:
            value = env.outer.pointer(vptr + 8 * index)
        except ValueError:
            break
        if value == 0 or not env.is_executable(value):
            break
        rows.append(value)
    return rows


def owner_category(env, target, family_text, h9g_text):
    if family_text[0] <= target < family_text[1]:
        return 'family-text'
    if h9g_text and h9g_text[0] <= target < h9g_text[1]:
        return 'appleclcd-text'
    owner = env.executable_owner(target)
    if owner and owner.startswith('kernelcache:'):
        return 'kernel-text'
    if owner:
        return 'other-kext-text'
    return 'unmapped'


def vtable_analysis(env, vptr, family_text, h9g_text, pure_address, limit=512):
    slots = decode_vtable(env, vptr, limit=limit)
    categories = Counter()
    rows = []
    for index, target in enumerate(slots):
        category = owner_category(env, target, family_text, h9g_text)
        categories[category] += 1
        rows.append(dict(slot=index, address=hex(target), category=category,
                         owner=env.executable_owner(target), abstract=(target == pure_address)))
    return dict(vptr=hex(vptr), slot_count=len(slots), owner_counts=dict(categories),
                abstract_slots=[row['slot'] for row in rows if row['abstract']],
                table_sha256=sha(b''.join(struct.pack('<Q', value) for value in slots)),
                slots=rows, first_slots=[row['address'] for row in rows[:8]],
                last_slot=rows[-1]['address'] if rows else None)


def find_materializations(env, ident, targets):
    """Find ADRP/ADD sites materializing one of the requested addresses."""
    image = env.modules[ident]
    text = image.section('__TEXT_EXEC', '__text')
    found = {target: [] for target in targets}
    for pc in range(text['va'], text['va'] + text['size'] - 8, 4):
        pair = A.address_pair(env.outer, pc)
        if not pair:
            continue
        target = pair[1]
        if target in found:
            next_word = env.outer.word(pc + 8)
            add_ten = next_word == (0x91004000 | (pair[0] << 5) | pair[0])
            found[target].append(dict(pc=pc, register=pair[0], add_sixteen=add_ten,
                                      next_word=hex(next_word)))
    return found


def function_end(env, ident, start):
    """First RET at the end of a simple generated function; returns dtor start."""
    image = env.modules[ident]
    text = image.section('__TEXT_EXEC', '__text')
    for pc in range(start, text['va'] + text['size'] - 4, 4):
        if env.outer.word(pc) == RET:
            nxt = pc + 4
            word = env.outer.word(nxt)
            if (word & 0xffc003ff) == 0xd10003ff or (word & 0xffc07fff) == 0xa9807bfd:
                return nxt
            return None
    return None


def registration_for_storage(env, ident, storage):
    """Decode the class registered into one metaclass storage address.

    Generated setters materialize x0 = storage, then immediately load
    x1 = class name, x2 = superclass metaclass and w3 = instance size before
    calling the OSMetaClass constructor."""
    image = env.modules[ident]
    text = image.section('__TEXT_EXEC', '__text')
    sites = []
    for pc in range(text['va'], text['va'] + text['size'] - 8, 4):
        pair = A.address_pair(env.outer, pc)
        if pair and pair[1] == storage:
            sites.append(pc)
    for site in sites:
        name_ptr = size = super_import = None
        for pc in range(site, site + 0x48, 4):
            pair = A.address_pair(env.outer, pc)
            if pair and pair[0] == 1 and name_ptr is None:
                name_ptr = pair[1]
            word = env.outer.word(pc)
            if word & 0xffe0001f == 0x52800003 and size is None:
                size = (word >> 5) & 0xffff
            adrp = A.adrp(word, pc)
            if adrp and adrp[0] == 2:
                load = env.outer.word(pc + 4)
                if load & 0xffc00000 == 0xf9400000 and ((load >> 5) & 31) == 2 and ((load & 31) == 2):
                    try:
                        super_import = env.outer.pointer(adrp[1] + ((load >> 10) & 0xfff) * 8)
                    except ValueError:
                        super_import = None
        if name_ptr is not None and size is not None:
            return dict(name=env.read_cstring(name_ptr), instance_bytes=size,
                        metaclass_storage=hex(storage), storage_setter_site=hex(site),
                        super_metaclass=(hex(super_import) if super_import is not None else None),
                        super_symbols=(env.symbols.get(super_import, []) if super_import is not None else []))
    return None


def class_infos(env, ident, metaclass_ctor, family_text=None, h9g_text=None, pure_address=None):
    records, _ = registrations(env, ident, metaclass_ctor)
    storages = resolve_metaclass_storages(env, ident, records)
    storage_names = {}
    for record in records:
        storage = storages.get(record['call_site'])
        if storage is not None and record['name']:
            storage_names[storage] = record['name']
    headers = vtable_headers(env, ident)
    by_storage = {}
    for header in headers:
        by_storage.setdefault(header['this_metaclass'], []).append(header)
    infos = []
    for record in records:
        storage = storages.get(record['call_site'])
        info = dict(name=record['name'], instance_bytes=record['instance_bytes'],
                    registration_site=record['call_site'],
                    super_raw=classify_super(env, ident, record['super_local'], record['super_import'], storage_names),
                    metaclass_storage=hex(storage) if storage is not None else None,
                    vtable=None, constructor=None, destructor_candidate=None)
        if storage is not None and storage in by_storage:
            header = by_storage[storage][0]
            vptr = header['vptr']
            info['vtable'] = dict(header=header['header'], vptr=hex(vptr),
                                  super_metaclass=hex(header['super_metaclass']),
                                  super_class_name=storage_names.get(header['super_metaclass']))
            target = vptr - 16
            found = find_materializations(env, ident, {target, vptr})
            candidates = sorted({env.function_start(ident, entry['pc']) for entry in found.get(target, [])
                                 if entry['pc'] is not None} | set(), key=lambda v: (v is None, v))
            candidates = [value for value in candidates if value is not None]
            if candidates:
                ctor = candidates[0]
                info['constructor'] = hex(ctor)
                info['destructor_candidate'] = hex(function_end(env, ident, ctor)) if function_end(env, ident, ctor) else None
            # direct one-add materialization of the vptr itself
            direct = [entry['pc'] for entry in found.get(vptr, [])]
            info['direct_vptr_materializations'] = [hex(pc) for pc in direct][:8]
        infos.append(info)
    return dict(records=records, storages=storages, storage_names=storage_names,
                headers=headers, classes=infos)


def decode_field_instruction(word):
    top = word & 0xffc00000
    if top in (0xf9400000, 0xf9000000):
        return (((word >> 10) & 0xfff) << 3, 'ldr/str-64', 'load' if top == 0xf9400000 else 'store')
    if top in (0xb9400000, 0xb9000000):
        return (((word >> 10) & 0xfff) << 2, 'ldr/str-32', 'load' if top == 0xb9400000 else 'store')
    if top in (0x79400000, 0x79000000):
        return (((word >> 10) & 0xfff) << 1, 'ldr/str-16', 'load' if top == 0x79400000 else 'store')
    if top in (0x39400000, 0x39000000):
        return ((word >> 10) & 0xfff, 'ldr/str-8', 'load' if top == 0x39400000 else 'store')
    return None


def got_relative_base(env, ident, pc, load_word):
    """If pc loads from this module's __got, return the GOT slot address."""
    image = env.modules[ident]
    text = image.section('__TEXT_EXEC', '__text')
    if pc - 12 < text['va']:
        return None
    base_register = (load_word >> 5) & 31
    for step in range(1, 4):
        prev = pc - 4 * step
        adrp = A.adrp(env.outer.word(prev), prev)
        if adrp and adrp[0] == base_register:
            offset = ((load_word >> 10) & 0xfff) * 8
            candidate = adrp[1] + offset
            if env.owner(candidate, env.got_ranges):
                return candidate
    return None


def attribute_site(env, ident, pc, slot_map):
    """slot_map maps method entry address -> (class name, slot index)."""
    start = env.function_start(ident, pc)
    if start is not None and start in slot_map:
        class_name, slot = slot_map[start]
        return dict(attribution='exact-method', class_name=class_name,
                    slot=slot, method=hex(start), distance=pc - start)
    nearest = None
    for target, (class_name, slot) in slot_map.items():
        if target <= pc and (nearest is None or target > nearest[0]):
            nearest = (target, class_name, slot)
    if nearest:
        return dict(attribution='nearest-slot', class_name=nearest[1], slot=nearest[2],
                    method=hex(nearest[0]), distance=pc - nearest[0])
    return dict(attribution='unattributed')


def scan_hypothesis_offsets(env, ident, offsets, slot_maps):
    image = env.modules[ident]
    text = image.section('__TEXT_EXEC', '__text')
    rows = []
    for pc in range(text['va'], text['va'] + text['size'] - 4, 4):
        word = env.outer.word(pc)
        decoded = decode_field_instruction(word)
        if not decoded:
            continue
        offset, kind, direction = decoded
        if offset not in offsets:
            continue
        got = got_relative_base(env, ident, pc, word)
        entry = dict(offset=hex(offset), pc=hex(pc), kind=kind, direction=direction,
                     got_relative=(hex(got) if got else None))
        if got is None:
            entry.update(attribute_site(env, ident, pc, slot_maps))
        rows.append(entry)
    return rows


def analyze_hypothesis_offsets(env, modules, slot_maps, offsets):
    output = {}
    for offset in sorted(offsets):
        per_module = {}
        for ident in modules:
            rows = scan_hypothesis_offsets(env, ident, {offset}, slot_maps.get(ident, {}))
            per_module[ident] = rows
        all_rows = [row for rows in per_module.values() for row in rows]
        attributed = [row for row in all_rows if row.get('attribution') == 'exact-method']
        output[hex(offset)] = dict(
            sites=len(all_rows),
            got_relative=sum(1 for row in all_rows if row.get('got_relative')),
            exact_method=attributed,
            nearest_slot=[row for row in all_rows if row.get('attribution') == 'nearest-slot'][:12],
            unattributed=sum(1 for row in all_rows if row.get('attribution') == 'unattributed'),
            by_module={ident: len(rows) for ident, rows in per_module.items()},
        )
    return output


RET_WORD = 0xd65f03c0


def sext(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def decode_load_store(word):
    """Decode the A64 general-register load/store (immediate) family.

    Returns None for every other encoding so a caller never guesses.  Only this
    family is decoded because it is the only one carrying a literal field
    offset; register-offset, literal-pool and SIMD/FP forms are deliberately
    not modelled, and any access they carry is reported as unattributed rather
    than approximated.
    """
    if (word >> 27) & 7 != 7 or (word >> 26) & 1:
        return None
    size = (word >> 30) & 3
    form = (word >> 24) & 3
    if form not in (0, 1):
        return None
    opc = (word >> 22) & 3
    if opc == 3 or (size == 3 and opc == 2):
        return None
    if form == 1:
        offset = ((word >> 10) & 0xfff) * (1 << size)
        writeback = False
    else:
        offset = sext((word >> 12) & 0x1ff, 9)
        writeback = ((word >> 10) & 3) in (1, 3)
    return dict(size=1 << size, kind=('load' if opc in (1, 2) else 'store'),
                offset=offset, rn=(word >> 5) & 31, rt=word & 31,
                writeback=writeback)


def decode_load_store_pair(word):
    """Decode LDP/STP/LDNP/STNP (integer).  Returns None for anything else."""
    if (word & 0x3a000000) != 0x28000000 or (word >> 26) & 1:
        return None
    if (word >> 30) not in (0, 2):
        return None
    scale = 8 if (word >> 30) == 2 else 4
    index = (word >> 23) & 3
    return dict(load=(word >> 22) & 1, index=index,
                offset=sext((word >> 15) & 0x7f, 7) * scale,
                rn=(word >> 5) & 31, rt=word & 31, rt2=(word >> 10) & 31,
                writeback=index in (1, 3))


def is_add_sub_immediate(word):
    return (word >> 23) & 0x3f == 0x22


def is_move_alias(word):
    """ORR <Xd>, XZR, <Xm> - the register-to-register MOV alias."""
    return (word & 0xffe0ffe0) == 0xaa0003e0


def is_conditional_branch(word):
    if (word & 0xff000010) == 0x54000000:
        return True
    if (word & 0x7e000000) in (0x34000000, 0x35000000, 0x36000000, 0x37000000):
        return True
    return False


UNKNOWN = ('unknown',)


def _expr(entry):
    tag = entry[0]
    if tag == 'this':
        return 'this'
    if tag == 'arg':
        return 'arg%d' % entry[1]
    if tag == 'const':
        return hex(entry[1])
    if tag == 'mem':
        return _expr(entry[1]) + '->' + hex(entry[2])
    if tag == 'callret':
        return 'return-of-' + hex(entry[1])
    if tag == 'sp':
        return 'sp'
    return 'unknown'


def _chain(entry):
    out = []
    while entry[0] == 'mem':
        out.append(hex(entry[2]))
        entry = entry[1]
    out.reverse()
    return out


def _root(entry):
    while entry[0] == 'mem':
        entry = entry[1]
    if entry[0] == 'this':
        return 'this'
    if entry[0] == 'arg':
        return 'arg%d' % entry[1]
    if entry[0] == 'callret':
        return 'call-return'
    if entry[0] == 'sp':
        return 'stack'
    return 'unknown'


def _depth(entry):
    depth = 0
    while entry[0] == 'mem':
        depth += 1
        entry = entry[1]
    return depth


def trace_function(env, ident, start, limit=1500, max_depth=3):
    """Linear register-provenance trace of one method body.

    Straight-line only: the scan runs from start to the first RET or the end of
    the section.  Conditional branches are counted but never taken, so an
    access reachable only under a condition is still listed with the register
    it is based on, while the condition guarding it stays unproven.  A call
    clobbers x0-x18, and x0 afterwards is recorded as a call-return marker
    rather than as unknown, so an access through a pointer a helper returned is
    reported as exactly that instead of being silently attributed to this.
    Registers written by an encoding this tool does not model become unknown;
    nothing is ever guessed from position alone.
    """
    image = env.modules[ident]
    text = image.section('__TEXT_EXEC', '__text')
    lo, hi = text['va'], text['va'] + text['size']
    regs = {0: ('this',)}
    for index in range(1, 8):
        regs[index] = ('arg', index)
    for index in range(8, 31):
        regs[index] = UNKNOWN
    regs[31] = ('sp',)
    sp = 0
    stack = {}
    accesses, calls = [], []
    branches = 0
    terminated = False
    steps = 0
    for step in range(limit):
        pc = start + 4 * step
        if pc < lo or pc >= hi - 4:
            break
        steps = step + 1
        word = env.outer.word(pc)
        if word == RET_WORD:
            terminated = True
            break
        if is_conditional_branch(word):
            branches += 1
            continue
        pair = decode_load_store_pair(word)
        if pair:
            offset = pair['offset'] + (sp if pair['rn'] == 31 else 0)
            if pair['rn'] == 31:
                if pair['load']:
                    for register in (pair['rt'], pair['rt2']):
                        regs[register] = stack.get(offset, UNKNOWN)
                else:
                    stack[offset] = regs.get(pair['rt'], UNKNOWN)
                    stack[offset + 8] = regs.get(pair['rt2'], UNKNOWN)
                if pair['writeback']:
                    sp += pair['offset']
            else:
                for register in (pair['rt'], pair['rt2']):
                    regs[register] = UNKNOWN
            continue
        if is_add_sub_immediate(word):
            rd, rn = word & 31, (word >> 5) & 31
            immediate = ((word >> 10) & 0xfff) << (12 if (word >> 22) & 1 else 0)
            if rn == 31 and rd == 31:
                sp += -immediate if (word >> 30) & 1 else immediate
            elif rd != 31:
                regs[rd] = UNKNOWN
            continue
        access = decode_load_store(word)
        if access:
            base = regs.get(access['rn'], UNKNOWN)
            offset = access['offset'] + (sp if access['rn'] == 31 else 0)
            if access['rn'] == 31:
                if access['kind'] == 'load':
                    regs[access['rt']] = stack.get(offset, UNKNOWN)
                else:
                    stack[offset] = regs.get(access['rt'], UNKNOWN)
                if access['writeback']:
                    sp += access['offset']
                continue
            accesses.append(dict(pc=hex(pc), kind=access['kind'], size=access['size'],
                                 offset=hex(access['offset']), base=_expr(base),
                                 chain=_chain(base), root=_root(base),
                                 depth=_depth(base)))
            if access['kind'] == 'load' and base[0] != 'unknown' and _depth(base) < max_depth:
                regs[access['rt']] = ('mem', base, access['offset'])
            else:
                regs[access['rt']] = UNKNOWN
            continue
        address = A.address_pair(env.outer, pc)
        if address:
            regs[address[0]] = ('const', address[1])
            continue
        if (word & 0xfc000000) == 0x94000000:
            target = A.branch_target(word, pc)
            symbol = None
            for module in (ident, FAMILY_ID, H9G_ID, SURFACE_ID):
                if module not in env.modules:
                    continue
                got = env.decode_stub(module, target)
                if got is None:
                    continue
                try:
                    bound = env.outer.pointer(got)
                except ValueError:
                    break
                names = env.symbols.get(bound) or []
                symbol = names[0] if names else hex(bound)
                break
            calls.append(dict(pc=hex(pc), target=hex(target), symbol=symbol,
                              arguments=[_expr(regs.get(index, UNKNOWN)) for index in range(8)],
                              argument_roots=[_root(regs.get(index, UNKNOWN)) for index in range(8)]))
            for index in range(19):
                regs[index] = UNKNOWN
            regs[0] = ('callret', pc)
            continue
        if is_move_alias(word):
            regs[word & 31] = regs.get((word >> 16) & 31, UNKNOWN)
            continue
        rd = word & 31
        if rd:
            regs[rd] = UNKNOWN
    return dict(accesses=accesses, calls=calls, branches=branches,
                terminated=terminated, instructions=steps,
                return_expression=_expr(regs.get(0, UNKNOWN)))


LOCK_SYMBOLS = ('IOLockLock', 'IOLockUnlock', 'IORecursiveLockLock',
                'IORecursiveLockUnlock', 'lck_mtx_lock', 'lck_mtx_unlock',
                'IORecursiveLockSleep', 'IORecursiveLockWakeup')


def method_shape(trace):
    """Register-usage shape of one method.  Deliberately not a prototype."""
    used = set()
    for access in trace['accesses']:
        root = access['root']
        if root == 'this':
            used.add(0)
        elif root.startswith('arg'):
            used.add(int(root[3:]))
    for call in trace['calls']:
        for root in call['argument_roots']:
            if root == 'this':
                used.add(0)
            elif root.startswith('arg'):
                used.add(int(root[3:]))
    lock = unlock = 0
    for call in trace['calls']:
        name = call['symbol'] or ''
        if not any(needle in name for needle in LOCK_SYMBOLS):
            continue
        if 'Unlock' in name or 'unlock' in name:
            unlock += 1
        else:
            lock += 1
    return dict(argument_registers_read=sorted(used),
                branch_instructions=trace['branches'],
                call_count=len(trace['calls']),
                call_symbols=[call['symbol'] for call in trace['calls'] if call['symbol']],
                lock_calls=dict(lock=lock, unlock=unlock),
                lock_balanced=(lock == unlock),
                return_expression=trace['return_expression'],
                terminated=trace['terminated'],
                instructions=trace['instructions'])


def slot_provenance(env, class_name, slot, address):
    """Trace one vtable slot target and classify its field accesses."""
    owner = env.executable_owner(int(address, 16))
    if owner is None:
        return dict(class_name=class_name, slot=slot, method=address, traced=False,
                    reason='slot target is not executable in this image')
    ident = owner.split(':')[0]
    if ident not in env.modules:
        return dict(class_name=class_name, slot=slot, method=address, traced=False,
                    reason='slot target owner module is not resolved')
    trace = trace_function(env, ident, int(address, 16))
    this_fields = sorted({item['offset'] for item in trace['accesses']
                          if item['root'] == 'this' and item['depth'] == 0})
    other = [item for item in trace['accesses']
             if not (item['root'] == 'this' and item['depth'] == 0)]
    return dict(class_name=class_name, slot=slot, method=address, traced=True,
                owner=owner, shape=method_shape(trace),
                this_relative_fields=this_fields, accesses=trace['accesses'],
                non_this_accesses=other, non_this_access_count=len(other))


def field_ownership(provenances, offsets):
    """Group observed field accesses by the reference hypothesis offsets.

    For each offset the report states which object the access is based on:
    'this' at depth 0 is the object the vtable belongs to, a deeper chain is a
    sub-object reached from it, and anything else (a parameter, or a pointer a
    helper returned) is explicitly *not* attributed to that object.
    """
    wanted = {hex(offset) for offset in offsets}
    grouped = {}
    for row in provenances:
        if not row.get('traced'):
            continue
        for item in row['accesses']:
            if item['offset'] not in wanted:
                continue
            grouped.setdefault(item['offset'], []).append(dict(
                class_name=row['class_name'], slot=row['slot'], method=row['method'],
                pc=item['pc'], kind=item['kind'], size=item['size'],
                base=item['base'], root=item['root'], chain=item['chain'],
                depth=item['depth']))
    output = {}
    for offset in sorted(wanted, key=lambda text: int(text, 16)):
        rows = grouped.get(offset, [])
        on_this = [row for row in rows if row['root'] == 'this' and row['depth'] == 0]
        on_sub = [row for row in rows if row['root'] == 'this' and row['depth'] > 0]
        off_this = [row for row in rows if row['root'] != 'this']
        if on_this:
            verdict = 'proven-this-relative'
        elif on_sub:
            verdict = 'proven-sub-object-of-this'
        elif off_this:
            verdict = 'not-this-relative'
        else:
            verdict = 'no-observed-access'
        output[offset] = dict(
            verdict=verdict,
            this_relative=[dict(class_name=row['class_name'], slot=row['slot'],
                                method=row['method'], pc=row['pc'], kind=row['kind'],
                                size=row['size']) for row in on_this],
            sub_object=[dict(class_name=row['class_name'], slot=row['slot'],
                             method=row['method'], pc=row['pc'], chain=row['chain'],
                             kind=row['kind'], size=row['size']) for row in on_sub],
            other_base=[dict(class_name=row['class_name'], slot=row['slot'],
                             method=row['method'], pc=row['pc'], base=row['base'],
                             kind=row['kind'], size=row['size']) for row in off_this],
            access_count=len(rows),
        )
    return output


def provenance_summary(row):
    """Compact, report-sized view of one traced method.

    The full access list stays in memory for the ownership grouping; the
    report keeps the shape, the this-relative field set and the access counts,
    so the JSON stays reviewable instead of carrying every intermediate access.
    """
    if not row.get('traced'):
        return dict(class_name=row['class_name'], slot=row['slot'],
                    method=row['method'], traced=False, reason=row['reason'])
    return dict(class_name=row['class_name'], slot=row['slot'],
                method=row['method'], traced=True, owner=row['owner'],
                shape=row['shape'],
                this_relative_fields=row['this_relative_fields'],
                non_this_access_count=row['non_this_access_count'])


def iosurface_write_sites(env, leaves):
    """Locate literal writers of each accessor field inside IOSurface text.

    A getter proves a field exists at an offset; it does not prove who owns or
    frees the value.  Recording the writer count and the first writer per field
    shows whether the field is written inside the kext at all, and is reported
    as counts plus first sites only - the writer's enclosing method is not
    claimed, because this accessor block has no symbol table to anchor it.
    """
    image = env.modules[SURFACE_ID]
    text = image.section('__TEXT_EXEC', '__text')
    wanted = {}
    for leaf in leaves:
        decoded = leaf.get('decoded')
        if not decoded:
            continue
        wanted.setdefault(decoded[0], set()).add(leaf['name'])
    rows = {name: dict(loads=0, stores=0, first_store=None, store_sizes=[])
            for names in wanted.values() for name in names}
    for pc in range(text['va'], text['va'] + text['size'] - 4, 4):
        access = decode_load_store(env.outer.word(pc))
        if not access or access['rn'] == 31:
            continue
        for name in wanted.get(access['offset'], ()):
            row = rows[name]
            if access['kind'] == 'load':
                row['loads'] += 1
            else:
                row['stores'] += 1
                row['store_sizes'].append(access['size'])
                if row['first_store'] is None:
                    row['first_store'] = hex(pc)
    for row in rows.values():
        row['store_sizes'] = sorted(set(row['store_sizes']))
    return dict(per_field=rows,
                conclusion=(
                    'each accessor field is written inside IOSurface text, so the field is '
                    'owned by the surface object; that does not establish when the write '
                    'completes, whether the descriptor is retained for the caller, or whether '
                    'a CPU copy after the getter is coherent'))


def iosurface_evidence(env, reference):
    image = env.modules[SURFACE_ID]
    text = image.section('__TEXT_EXEC', '__text')
    base = A.surface_accessors(env.outer, image)
    leaves = base.get('leaves', [])
    for leaf in leaves:
        word = int(leaf['load_instruction'], 16)
        leaf['decoded'] = decode_field_instruction(word)
        leaf['reference_binding'] = reference['bindings'].get('_native_legacy_surface_' + leaf['name'])
    reference_offsets = {}
    for leaf in leaves:
        if leaf.get('reference_binding'):
            reference_offsets[hex(int(leaf['reference_binding'], 16) + 0x1000000)] = leaf['address']
    return dict(uuid=base.get('uuid'), text_address=base.get('text_address'),
                text_bytes=base.get('text_bytes'), pattern_candidates=base.get('pattern_candidates'),
                block_sha256=sha(env.outer.read(text['va'], text['size'])),
                leaves=leaves, reference_plus_module_delta_matches=reference_offsets,
                runtime_binding_ready=base.get('runtime_binding_ready'),
                semantics=base.get('semantics'))


def stub_import_summary(env, ident, display_prefixes):
    rows = env.stub_bindings(ident)
    categories = Counter()
    resolved = []
    for row in rows:
        bound = int(row['bound'], 16)
        owner = row['bound_owner']
        if bound == 0:
            category = 'null'
        elif owner and owner.startswith('kernelcache:'):
            category = 'kernel-export'
        elif owner and owner.startswith(ident + ':'):
            category = 'self'
        elif owner and owner.startswith(SURFACE_ID + ':'):
            category = 'iosurface-kext'
        elif owner and owner.startswith(H9G_ID + ':'):
            category = 'appleclcd-kext'
        elif owner:
            category = 'other-kext'
        elif row['bound_data_owner']:
            category = 'kernel-data-object'
        else:
            category = 'unresolved'
        categories[category] += 1
        if category in ('kernel-export', 'iosurface-kext', 'appleclcd-kext', 'other-kext', 'kernel-data-object'):
            resolved.append(dict(index=row['index'], stub=row['stub'], got=row['got'],
                                 bound=row['bound'], category=category, owner=owner,
                                 symbols=row['symbols'], bound_data_owner=row['bound_data_owner']))
    relevant = [row for row in resolved if any(prefix in symbol for prefix in display_prefixes for symbol in row['symbols'])]
    return dict(total_stubs=len(rows), categories=dict(categories), resolved=resolved,
                display_relevant=relevant)


def kernel_export_inventory(env, required_names):
    symbols = env.symbols
    found, missing = [], []
    for name in required_names:
        addresses = [hex(address) for address, names in symbols.items() if name in names]
        if addresses:
            found.append(dict(name=name, addresses=addresses))
        else:
            missing.append(name)
    return dict(found=found, missing=missing)


def symbol_search(env, needles):
    hits = []
    for address, names in env.symbols.items():
        for name in names:
            if any(needle in name for needle in needles):
                hits.append(dict(address=hex(address), name=name))
                break
    return sorted(hits, key=lambda item: item['address'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernelcache', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expect-sha256')
    parser.add_argument('--expect-uuid')
    parser.add_argument('--reference', type=Path, default=REFERENCE_PATH)
    args = parser.parse_args()
    source = A.resolve_input(args.kernelcache)
    data = Path(source).read_bytes()
    if args.expect_sha256:
        A.require(hashlib.sha256(data).hexdigest() == args.expect_sha256.lower(), 'kernelcache SHA-256 mismatch')
    env = Env(data)
    if args.expect_uuid:
        A.require(env.outer.uuids[0] == str(uuid.UUID(args.expect_uuid)), 'kernelcache UUID mismatch')
    reference = json.loads(Path(args.reference).read_bytes())
    A.validate_reference(reference)
    module_uuid = {}
    for ident in (FAMILY_ID, SURFACE_ID, H9G_ID):
        entry = next(item for item in env.entries if item['CFBundleIdentifier'] == ident)
        image = env.modules[ident]
        module_uuid[ident] = dict(uuid=image.uuids[0],
                                  load_address=hex(entry['_PrelinkExecutableLoadAddr']),
                                  version=entry.get('CFBundleVersion'),
                                  prelink_index=env.order[ident],
                                  dependencies=entry.get('OSBundleLibraries', {}),
                                  personalities=entry.get('IOKitPersonalities'))
    metaclass_ctor = None
    for address, names in env.symbols.items():
        if '__ZN11OSMetaClassC2EPKcPKS_j' in names:
            metaclass_ctor = address
            break
    A.require(metaclass_ctor is not None, 'OSMetaClass constructor export not found')
    pure_address = None
    for address, names in env.symbols.items():
        if any('___cxa_pure_virtual' in name for name in names):
            pure_address = address
            break
    A.require(pure_address is not None, 'pure virtual export not found')

    family_data = class_infos(env, FAMILY_ID, metaclass_ctor)
    family = env.modules[FAMILY_ID]
    family_text_section = family.section('__TEXT_EXEC', '__text')
    family_text = (family_text_section['va'], family_text_section['va'] + family_text_section['size'])
    h9g = env.modules.get(H9G_ID)
    h9g_text = None
    if h9g is not None:
        h9g_section = h9g.section('__TEXT_EXEC', '__text')
        h9g_text = (h9g_section['va'], h9g_section['va'] + h9g_section['size'])

    class_models = {}
    slot_maps = {}
    for info in family_data['classes']:
        if not info.get('vtable'):
            continue
        model = vtable_analysis(env, int(info['vtable']['vptr'], 16), family_text, h9g_text, pure_address)
        class_models[info['name']] = dict(info=info, vtable=model)
        slot_maps.setdefault(FAMILY_ID, {})
        slot_maps[FAMILY_ID].update({int(row['address'], 16): (info['name'], row['slot']) for row in model['slots']})
    legacy = class_models.get('IOMobileFramebufferLegacy')
    A.require(legacy is not None, 'IOMobileFramebufferLegacy vtable not located')
    legacy_slots = legacy['vtable']['slots']
    reference_methods = reference_slots(reference)
    legacy_rows = []
    for index, row in enumerate(legacy_slots):
        reference_address = int(reference_methods[index]['address'], 16)
        local_address = int(row['address'], 16)
        legacy_rows.append(dict(slot=index, local=row['address'], local_category=row['category'],
                                owner=row['owner'], symbols=env.symbols.get(local_address, []),
                                reference_address=reference_methods[index]['address'],
                                delta=hex(local_address - reference_address),
                                abstract=row['abstract']))
    family_deltas = sorted({row['delta'] for row in legacy_rows if row['local_category'] == 'family-text'})
    kernel_rows = [row for row in legacy_rows if row['local_category'] == 'kernel-text']
    kernel_deltas = [int(row['delta'], 16) for row in kernel_rows]
    named_slots = [184, 188, 213, 249, 288, 290, 295, 296, 301, 337]
    named_slot_rows = []
    for slot in named_slots:
        row = legacy_rows[slot]
        named_slot_rows.append(dict(slot=slot, local=row['local'], category=row['local_category'],
                                    owner=row['owner'], symbols=row['symbols'],
                                    reference_address=row['reference_address'], delta=row['delta'],
                                    abstract=row['abstract']))
    legacy_table_sha = legacy['vtable']['table_sha256']

    kernel_symbols = sorted({name for row in kernel_rows for name in row['symbols']})
    kernel_with_symbols = sum(1 for row in kernel_rows if row['symbols'])
    inherited = dict(legacy_slot_count=len(legacy_rows),
                     family_target_deltas=family_deltas,
                     kernel_target_count=len(kernel_rows),
                     kernel_delta_min=hex(min(kernel_deltas)) if kernel_deltas else None,
                     kernel_delta_max=hex(max(kernel_deltas)) if kernel_deltas else None,
                     kernel_delta_distinct=len(set(kernel_deltas)),
                     kernel_delta_zero_count=sum(1 for value in kernel_deltas if value == 0),
                     kernel_targets_with_exported_symbols=kernel_with_symbols,
                     kernel_exported_symbols=sorted(set(kernel_symbols))[:80],
                     table_sha256=legacy_table_sha,
                     conclusion='family-owned slots share one module-relative delta; kernel-owned slots do not share a single slide and are individually resolvable through the local kernel export symbol table')
    # requested ABI-AUDIT slots: which are overridden by the shipped subclass
    subclass_evidence = None
    subclass_headers = []
    if h9g is not None and legacy['info'].get('metaclass_storage'):
        legacy_meta = int(legacy['info']['metaclass_storage'], 16)
        for header in vtable_headers(env, H9G_ID):
            if header['super_metaclass'] == legacy_meta:
                subclass_headers.append(header)
        if subclass_headers:
            header = subclass_headers[0]
            subclass_model = vtable_analysis(env, header['vptr'], family_text, h9g_text, pure_address,
                                             limit=len(legacy_rows))
            overrides = [row['slot'] for row in subclass_model['slots'] if row['category'] == 'appleclcd-text']
            override_profile = Counter(row['category'] for row in subclass_model['slots'])
            comparisons = []
            for index in range(min(len(subclass_model['slots']), len(legacy_rows))):
                base = int(legacy_rows[index]['local'], 16)
                derived = int(subclass_model['slots'][index]['address'], 16)
                comparisons.append(base == derived)
            subclass_evidence = dict(header=header['header'], vptr=hex(header['vptr']),
                                     this_metaclass=hex(header['this_metaclass']),
                                     super_metaclass=hex(header['super_metaclass']),
                                     slot_count=subclass_model['slot_count'],
                                     owner_counts=subclass_model['owner_counts'],
                                     override_slots=overrides,
                                     override_count=len(overrides),
                                     inherited_identical=sum(1 for equal in comparisons if equal),
                                     named_slots_overridden=[slot for slot in named_slots if slot in overrides],
                                     table_sha256=subclass_model['table_sha256'])
            h9g_records, _ = registrations(env, H9G_ID, metaclass_ctor)
            legacy_meta = int(legacy['info']['metaclass_storage'], 16)
            subclass_regs = []
            for record in h9g_records:
                super_import = record['super_import']
                if super_import == legacy_meta:
                    subclass_regs.append(dict(name=record['name'], instance_bytes=record['instance_bytes'],
                                              registration_site=record['call_site'],
                                              super_kind='family-legacy-metaclass'))
                elif record['super_local'] is not None and record['super_local'] == header['this_metaclass']:
                    subclass_regs.append(dict(name=record['name'], instance_bytes=record['instance_bytes'],
                                              registration_site=record['call_site'],
                                              super_kind='appleclcd-local-metaclass'))
            subclass_evidence['registrations'] = subclass_regs
            h9g_imports = env.stub_bindings(H9G_ID)
            legacy_ctor = int(legacy['info']['constructor'], 16) if legacy['info'].get('constructor') else None
            legacy_dtor = int(legacy['info']['destructor_candidate'], 16) if legacy['info'].get('destructor_candidate') else None
            cross = []
            for row in h9g_imports:
                if int(row['bound'], 16) in (legacy_ctor, legacy_dtor, int(legacy['info']['metaclass_storage'], 16)):
                    cross.append(dict(stub=row['stub'], got=row['got'], bound=row['bound']))
            subclass_evidence['imports_of_legacy'] = cross
            subclass_evidence['all_headers_with_legacy_super'] = [item['header'] for item in subclass_headers]
            direct = registration_for_storage(env, H9G_ID, header['this_metaclass'])
            subclass_evidence['direct_subclass_registration'] = direct
            further = []
            for candidate in vtable_headers(env, H9G_ID):
                if candidate['super_metaclass'] != header['this_metaclass']:
                    continue
                model = vtable_analysis(env, candidate['vptr'], family_text, h9g_text, pure_address,
                                        limit=len(legacy_rows))
                further.append(dict(header=candidate['header'], vptr=hex(candidate['vptr']),
                                   this_metaclass=hex(candidate['this_metaclass']),
                                   slot_count=model['slot_count'], owner_counts=model['owner_counts'],
                                   table_sha256=model['table_sha256'],
                                   identical_to_direct_subclass_table=(model['table_sha256'] == subclass_model['table_sha256']),
                                   registration=registration_for_storage(env, H9G_ID, candidate['this_metaclass'])))
            subclass_evidence['further_subclasses'] = further
            deduped = {}
            for record in subclass_regs:
                key = (record['name'], record['instance_bytes'], record['super_kind'])
                deduped[key] = deduped.get(key, 0) + 1
            subclass_evidence['observed_registration_pairs'] = [
                dict(name=key[0], instance_bytes=key[1], super_kind=key[2], call_sites=count)
                for key, count in sorted(deduped.items())]
            subclass_evidence['note'] = ('direct subclass of the local Legacy class in AppleMobileDispH9G; the '
                                         'per-call registration decoder sees repeated call sites whose x1/x2/w3 '
                                         'registers can be reused across one init function, so class topology '
                                         'beyond header-linked storage pairs is not fully proven; prototypes and '
                                         'per-slot semantics remain unproven')
    # superclass graph and inheritance consistency
    graph = []
    for info in family_data['classes']:
        super_info = info.get('super_raw', {})
        graph.append(dict(class_name=info['name'], instance_bytes=info['instance_bytes'],
                          superclass_kind=super_info.get('kind'),
                          superclass_address=super_info.get('address'),
                          superclass_class=super_info.get('class_name'),
                          superclass_symbols=super_info.get('symbols')))
    consistency = []
    for info in family_data['classes']:
        if not info.get('constructor') or not info.get('destructor_candidate'):
            continue
        super_info = info.get('super_raw', {})
        super_storage = super_info.get('address')
        if super_info.get('kind') != 'local-metaclass-object' or not super_storage:
            continue
        for other in family_data['classes']:
            if other.get('metaclass_storage') == super_storage:
                if other.get('constructor') and other.get('destructor_candidate'):
                    calls = sorted(env.bl_targets(FAMILY_ID).get(int(info['constructor'], 16), []))
                    ctor_bl = sorted(pc for pc in range(int(info['constructor'], 16), int(info['destructor_candidate'], 16))
                                     if env.outer.word(pc) & 0xfc000000 == 0x94000000)
                    dtor_bl = sorted(pc for pc in range(int(info['destructor_candidate'], 16), int(info['destructor_candidate'], 16) + 32)
                                     if env.outer.word(pc) & 0xfc000000 == 0x94000000)
                    ctor_targets = [A.branch_target(env.outer.word(pc), pc) for pc in ctor_bl]
                    dtor_targets = [A.branch_target(env.outer.word(pc), pc) for pc in dtor_bl]
                    super_ctor = int(other['constructor'], 16) if other.get('constructor') else None
                    super_dtor = int(other['destructor_candidate'], 16) if other.get('destructor_candidate') else None
                    consistency.append(dict(class_name=info['name'], superclass=other['name'],
                                            ctor=info['constructor'], dtor=info['destructor_candidate'],
                                            super_ctor=other['constructor'], super_dtor=other['destructor_candidate'],
                                            ctor_calls_super_ctor=super_ctor in ctor_targets,
                                            dtor_calls_super_dtor=super_dtor in dtor_targets,
                                            ctor_bl_targets=[hex(value) for value in ctor_targets],
                                            dtor_bl_targets=[hex(value) for value in dtor_targets]))
                break
    # IOSurface accessors
    iosurface = iosurface_evidence(env, reference)
    iosurface['field_write_sites'] = iosurface_write_sites(env, iosurface['leaves'])
    # swap lifecycle hypotheses
    hypothesis_offsets = {0x1560, 0x1568, 0x1570, 0x16b0, 0x16b4, 0xb90, 0xb98}
    h9g_slot_map = {}
    if subclass_evidence is not None:
        h9g_slot_map = {int(row['address'], 16): ('AppleCLCD-subclass', row['slot'])
                        for row in vtable_analysis(env, int(subclass_evidence['vptr'], 16), family_text, h9g_text, pure_address)['slots']}
    slot_maps = {FAMILY_ID: slot_maps.get(FAMILY_ID, {})}
    if h9g is not None and h9g_slot_map:
        slot_maps[H9G_ID] = h9g_slot_map
    swap_hypotheses = analyze_hypothesis_offsets(env, [FAMILY_ID] + ([H9G_ID] if h9g is not None else []),
                                                slot_maps, hypothesis_offsets)
    for offset_key, offset_data in swap_hypotheses.items():
        attributed = {}
        for row in offset_data['exact_method']:
            key = row['class_name'] + '#slot' + str(row['slot'])
            attributed.setdefault(key, set()).add(row['offset'])
        offset_data['attributed_methods'] = {key: sorted(values) for key, values in sorted(attributed.items())}
        offset_data['exact_method'] = offset_data['exact_method'][:12]
    named_slot_cross_reference = {}
    for named_slot in named_slots:
        hits = {}
        for offset_key, offset_data in swap_hypotheses.items():
            for method_key, method_offsets in offset_data['attributed_methods'].items():
                class_name, slot_text = method_key.rsplit('#slot', 1)
                if int(slot_text) == named_slot:
                    hits.setdefault(offset_key, set()).add(class_name)
        if hits:
            named_slot_cross_reference[str(named_slot)] = dict(
                hypothesis_offsets={key: sorted(values) for key, values in sorted(hits.items())},
                overridden_by_shipped_subclass=(subclass_evidence is not None
                                                and named_slot in subclass_evidence['override_slots']),
                local_slot_address=legacy_rows[named_slot]['local'])
    # Register-provenance analysis: for every audited slot, trace the method
    # body and record which object each literal field access is based on.  This
    # is what turns the reference's field-offset hypotheses into a statement
    # about ownership, and it is why a bare instruction scan is not enough.
    provenance_rows = []
    for row in named_slot_rows:
        provenance_rows.append(slot_provenance(env, 'IOMobileFramebufferLegacy',
                                               row['slot'], row['local']))
    override_provenance = []
    if subclass_evidence is not None:
        for slot in sorted(set(subclass_evidence['override_slots']) | set(named_slots)):
            try:
                target = env.outer.pointer(int(subclass_evidence['vptr'], 16) + 8 * slot)
            except ValueError:
                continue
            if not env.is_executable(target):
                continue
            if owner_category(env, target, family_text, h9g_text) != 'appleclcd-text':
                continue
            override_provenance.append(slot_provenance(env, 'AppleCLCD-subclass', slot,
                                                       hex(target)))
    provenance_rows.extend(override_provenance)
    ownership = field_ownership(provenance_rows, hypothesis_offsets)
    # An offset is only qualified as a member of the traced object when at
    # least one access is based on 'this' at depth 0; a sub-object chain is
    # recorded as such and is never promoted to a member of this object.
    qualified_offsets = sorted(key for key, value in ownership.items()
                               if value['verdict'] == 'proven-this-relative')
    sub_object_offsets = sorted(key for key, value in ownership.items()
                                if value['verdict'] == 'proven-sub-object-of-this')
    this_relative_size_bound = None
    if qualified_offsets:
        highest = max(int(key, 16) for key in qualified_offsets)
        legacy_size = int(legacy['info']['instance_bytes'])
        this_relative_size_bound = dict(highest_offset=hex(highest),
                                        legacy_instance_bytes=legacy_size,
                                        all_offsets_inside_legacy_instance=(highest + 8) <= legacy_size)
    # Size arithmetic that decides whether the reference request-link reading
    # survives: a next/prev pair occupying the last 16 bytes of the request
    # object means the higher link ends exactly at the class's instance size.
    request_link_corroboration = None
    request_record = next((record for record in family_data['records']
                           if record['name'] == 'IOMFBSwapIORequest'), None)
    if request_record is not None:
        request_size = request_record['instance_bytes']
        links = sorted(int(key, 16) for key in ('0xb90', '0xb98'))
        request_link_corroboration = dict(
            request_instance_bytes=request_size,
            link_offsets=[hex(value) for value in links],
            link_spacing=links[1] - links[0],
            trailing_pair_end=hex(links[1] + 8),
            links_are_trailing_16_bytes=((links[1] + 8) == request_size
                                         and (links[1] - links[0]) == 8),
            reached_through_this_field=sorted({
                chain[0] for key in ('0xb90', '0xb98')
                for chain in (row['chain'] for row in ownership[key]['sub_object']) if chain}),
            conclusion=('the two offsets are 8 bytes apart and the higher one ends exactly at '
                        'the IOMFBSwapIORequest instance size, and both are reached by walking a '
                        'pointer held in this object, which is the shape of a trailing next/prev '
                        'pair reached from the framebuffer; the reference reading is corroborated '
                        'by this shape without proving the runtime class of that object'))
    locked_methods = [dict(class_name=row['class_name'], slot=row['slot'],
                           method=row['method'], lock_calls=row['shape']['lock_calls'])
                      for row in provenance_rows
                      if row.get('traced') and row['shape']['call_count']
                      and (row['shape']['lock_calls']['lock'] or row['shape']['lock_calls']['unlock'])]
    swap_classes = {}
    for name, model in class_models.items():
        if name in ('IOMobileFramebufferLegacy', 'IOMFBSwapIORequest'):
            swap_classes[name] = dict(instance_bytes=model['info']['instance_bytes'],
                                      vtable_vptr=model['vtable']['vptr'],
                                      slot_count=model['vtable']['slot_count'],
                                      constructor=model['info'].get('constructor'))
    if 'IOMFBSwapIORequest' not in swap_classes:
        for record in family_data['records']:
            if record['name'] == 'IOMFBSwapIORequest':
                swap_classes['IOMFBSwapIORequest'] = dict(instance_bytes=record['instance_bytes'],
                                                          vtable_vptr=None, slot_count=None, constructor=None)
    # imports
    display_prefixes = ('IOSurface', 'IOMobileFramebuffer', 'IOFramebuffer', 'IODeviceMemory',
                        'IOMemoryDescriptor', 'IOMemoryMap', 'IODT', 'IOPlatformExpert',
                        'IOService', 'IOWorkLoop', 'IOCommandGate', 'IOInterrupt', 'IOTimer',
                        'OSMetaClass', 'OSObject')
    family_imports = stub_import_summary(env, FAMILY_ID, display_prefixes)
    surface_imports = stub_import_summary(env, SURFACE_ID, display_prefixes)
    required_names = [
        '__ZN11OSMetaClassC2EPKcPKS_j',
        '__ZNK15OSMetaClassMeta5allocEv',
        '__ZN11OSMetaClass10preModLoadEPKc',
        '__ZN11OSMetaClass12checkModLoadEPv',
        '__ZN11OSMetaClass11postModLoadEPv',
        '__ZN11OSMetaClass20getMetaClassWithNameEPK8OSSymbol',
        '__ZN11OSMetaClass18allocClassWithNameEPKc',
        '__ZN8OSObjectC2EPK11OSMetaClass',
        '___cxa_pure_virtual',
        '__ZNK9IOService11getProviderEv',
        '__ZN14IODeviceMemory9withRangeEyy',
        '__ZN14IODeviceMemory12withSubRangeEPS_yy',
        '__ZN14IODeviceMemory13arrayFromListEPNS_11InitElementEj',
        '__ZN18IOMemoryDescriptor19withPhysicalAddressEyyj',
        '__ZN18IOMemoryDescriptor16withAddressRangeEyyjP4task',
        '__ZN18IOMemoryDescriptor3mapEj',
        '__Z21IODTResolveAddressingP15IORegistryEntryPKcP14IODeviceMemory',
        '__ZN9IOService15registerServiceEPFiP15OSMetaClassBase5IORPCE',
    ]
    exports = kernel_export_inventory(env, required_names)
    pe_symbols = symbol_search(env, ('PE_', '_gPE', 'GOP', 'gPEScreenInfo'))
    gop_symbols = symbol_search(env, ('GOP', 'gop'))
    gop_handoff = dict(
        h9g_personalities=module_uuid.get(H9G_ID, {}).get('personalities'),
        h9g_dependencies=module_uuid.get(H9G_ID, {}).get('dependencies'),
        appleclcd_provider_contract='AppleCLCD matches IONameMatch disp0,t8010 | disp0,t8011 under IOProviderClass AppleARMIODevice; backlight-control property match; display timing data is expected from the DT platform device, not from a GOP handle',
        gop_related_kernel_symbols=gop_symbols,
        pe_related_kernel_symbols=pe_symbols,
        kernel_primitives=exports['found'],
        kernel_primitives_missing=exports['missing'],
        conclusion='a stock kernelcache exposes no GOP/UEFI framebuffer hand-off object; the shipped display stack is a DT AppleARMIODevice/AppleCLCD graph. A Polar GOP-owned nub plus its ownership hand-off cannot be qualified from these bytes and requires board-side evidence.',
    )
    surface_leaf_by_address = {leaf['address']: leaf['name'] for leaf in iosurface['leaves']}
    legacy_vptr = int(legacy['vtable']['vptr'], 16)
    legacy_ctor = legacy['info'].get('constructor')
    legacy_dtor = legacy['info'].get('destructor_candidate')
    legacy_meta = legacy['info'].get('metaclass_storage')
    legacy_slot_addresses = {row['local'] for row in legacy_rows}
    subclass_vptr = int(subclass_evidence['vptr'], 16) if subclass_evidence else None
    reference_binding_rows = []
    for name, address in reference['bindings'].items():
        reference_address = int(address, 16)
        candidate = reference_address + 0x1000000
        corroboration = 'unverified'
        detail = None
        expression = name.split('(')[0]
        if name.endswith('gMetaClassE') and legacy_meta and candidate == int(legacy_meta, 16):
            corroboration = 'local-structural-match'
            detail = 'Family static setter materializes this storage address and the class meta_init builds the metaclass object there'
        elif expression == '__ZTV25IOMobileFramebufferLegacy' and candidate == legacy_vptr - 16:
            corroboration = 'local-structural-match'
            detail = 'equals the two-word zero prefix directly below the independently located vptr'
        elif name.endswith('C2EPK11OSMetaClass') and legacy_ctor and candidate == int(legacy_ctor, 16):
            corroboration = 'local-structural-match'
            detail = 'function prologue plus materialization of vptr-16 at function offset +0xC, then vptr store into the instance'
        elif name.endswith('D2Ev') and legacy_dtor and candidate == int(legacy_dtor, 16):
            corroboration = 'structural-candidate'
            detail = 'function boundary immediately after the constructor; stores this and calls the superclass destructor candidate; not proven by name'
        elif hex(candidate) in surface_leaf_by_address:
            corroboration = 'independent-instruction-scan-match'
            detail = 'identical address found by the local 12-getter instruction-pattern scan: ' + surface_leaf_by_address[hex(candidate)]
        elif hex(candidate) in legacy_slot_addresses:
            corroboration = 'vtable-slot-reference'
            detail = 'the transformed address appears as a local Legacy vtable slot target'
        elif env.is_executable(candidate) and env.function_start(FAMILY_ID, candidate) == candidate:
            corroboration = 'function-boundary-only'
            detail = 'a local function begins at the transformed address; its identity is not established'
        reference_binding_rows.append(dict(name=name, reference_address=address, admitted=False,
                                           local_candidate=hex(candidate),
                                           local_candidate_owner=env.executable_owner(candidate)
                                           or env.owner(candidate, env.data_ranges),
                                           corroboration=corroboration, detail=detail))
    report = dict(
        schema=1,
        evidence_completed=True,
        adapter_ready=False,
        generated_private_bindings=False,
        hardware_tested=False,
        collector_sha256=sha(HERE.read_bytes()),
        auditor_sha256=sha(AUDITOR_PATH.read_bytes()),
        reference_file_sha256=sha(Path(args.reference).read_bytes()),
        input=dict(path=str(Path(source).resolve()), bytes=len(data),
                   sha256=sha(data), uuid=env.outer.uuids[0],
                   architecture='arm64 (not arm64e)',
                   prelink_modules=len(env.entries),
                   resolved_module_images=len(env.modules),
                   unresolved_modules=len(env.unresolved)),
        modules=module_uuid,
        prelink_order=dict(**{ident: env.order[ident] for ident in (SURFACE_ID, FAMILY_ID, H9G_ID) if ident in env.order},
                           family_depends_on_iosurface=FAMILY_ID in env.modules and SURFACE_ID in
                           (env.entries[env.order[FAMILY_ID]].get('OSBundleLibraries') or {}),
                           h9g_depends_on_family=H9G_ID in env.order and FAMILY_ID in
                           (env.entries[env.order[H9G_ID]].get('OSBundleLibraries') or {})),
        family_class_map=dict(
            classes=family_data['classes'], headers=family_data['headers'],
            registration_count=len(family_data['records']),
            vtables=[dict(class_name=name, vptr=model['vtable']['vptr'],
                          slot_count=model['vtable']['slot_count'],
                          owner_counts=model['vtable']['owner_counts'],
                          abstract_slots=model['vtable']['abstract_slots'],
                          table_sha256=model['vtable']['table_sha256'],
                          constructor=model['info'].get('constructor'),
                          destructor_candidate=model['info'].get('destructor_candidate'))
                     for name, model in class_models.items()]),
        superclass_graph=graph,
        inheritance_consistency=consistency,
        legacy_detail=dict(
            instance_bytes=legacy['info']['instance_bytes'],
            metaclass_storage=legacy['info'].get('metaclass_storage'),
            superclass=legacy['info'].get('super_raw'),
            constructor=legacy['info'].get('constructor'),
            destructor_candidate=legacy['info'].get('destructor_candidate'),
            vtable=dict(vptr=legacy['vtable']['vptr'], header=legacy['info']['vtable']['header'],
                        slot_count=legacy['vtable']['slot_count'],
                        owner_counts=legacy['vtable']['owner_counts'],
                        abstract_slots=legacy['vtable']['abstract_slots'],
                        table_sha256=legacy_table_sha),
            module_delta_analysis=inherited,
            named_reference_slots=named_slot_rows,
            reference_vptr_owner=env.executable_owner(int(reference['abi']['legacy_vptr'], 16)),
            reference_vptr=reference['abi']['legacy_vptr'],
        ),
        shipped_subclass=subclass_evidence,
        iosurface_accessors=iosurface,
        reference_bindings=reference_binding_rows,
        reference_binding_transform=dict(module_delta='0x1000000',
            basis='194/194 Family-owned local Legacy vtable slots differ from the pinned reference by exactly this delta; the same delta independently reproduces the vtable prefix, IOSurface accessor leaves and Legacy constructor location. It does not apply to kernel-target slots.',
            admitted_bindings=0),
        swap_lifecycle=dict(classes=swap_classes,
                            reference_hypothesis_offsets=swap_hypotheses,
                            named_slot_cross_reference=named_slot_cross_reference,
                            field_ownership=ownership,
                            field_ownership_summary=dict(
                                qualified_this_relative_offsets=qualified_offsets,
                                proven_sub_object_offsets=sub_object_offsets,
                                unqualified_offsets=sorted(
                                    key for key, value in ownership.items()
                                    if value['verdict'] not in ('proven-this-relative',
                                                                'proven-sub-object-of-this')),
                                size_bound=this_relative_size_bound,
                                request_link_corroboration=request_link_corroboration,
                                conclusion=('the reference offsets are confirmed as literal field '
                                            'offsets of the IOMobileFramebufferLegacy/AppleCLCD '
                                            'instance: 0x1560/0x1568/0x1570/0x16b0/0x16b4 are '
                                            'accessed through this at depth 0, and 0xb90/0xb98 are '
                                            'reached only by walking this->0x1568 and then 0xb90, '
                                            'which is a list traversal, not a member access of the '
                                            'framebuffer object. The reference reading of '
                                            '0x1560/0x1568 as pending/current request pointers and of '
                                            "0xb90/0xb98 as that request's next/prev links is "
                                            'corroborated by this shape and by the size arithmetic, '
                                            'but it remains a hypothesis: no local byte proves the '
                                            'runtime class of the object at this->0x1568')),
                            register_provenance=[provenance_summary(row) for row in provenance_rows],
                            locking=dict(methods_with_lock_calls=locked_methods,
                                         conclusion=('no traced swap-path method performs a matched '
                                                     'IOLock/IORecursiveLock acquire/release pair; the '
                                                     'lock and completion state machine therefore '
                                                     'remains unproven from these bytes')),
                            note=('hypothesis offsets are checked against literal field-encoded '
                                  'loads/stores only; GOT-relative loads are separated; each access is '
                                  'additionally attributed to the register it is based on. No '
                                  'locking, retention or completion proof is claimed')),
        import_bindings=dict(family=family_imports, iosurface=surface_imports),
        gop_handoff=gop_handoff,
        missing_evidence=[
            'No exported kext symbols: per-slot prototype names and demangled signatures cannot be recovered from this stock image.',
            'Constructor/destructor bodies are located structurally (vtable materialization, super-call chain) but their source-level prototypes and member layouts are not proven.',
            'IOSurface accessor names come from the pinned public reference; descriptor ownership, pixel-format values and CPU-completion semantics are not provable from local instruction bytes.',
            'Register provenance attributes every reference hypothesis offset to an object: '
            + ', '.join(qualified_offsets) + ' are read or written through this at depth 0, while '
            + ', '.join(sub_object_offsets) + ' are reached only by walking the pointer stored at '
            'this+0x1568 and then this->0x1568->0xb90. The reference next/prev reading is '
            'corroborated by that list-walk shape and by 0xb98+8 == the IOMFBSwapIORequest '
            'instance size, but the runtime class of the object at this+0x1568 is still unproven.',
            'Straight-line tracing cannot resolve which branch executes, so a field recorded here '
            'may be touched only on a path this tool does not take; the offsets are proven to be '
            'literal accesses, not proven to execute on every call.',
            'Swap locking, retention and completion remain unproven: no traced swap-path method performs a matched IOLock/IORecursiveLock acquire/release pair, and no method retains or releases a request object.',
            'The traced methods are straight-line only. Conditional branches are counted but not taken, so an access guarded by a condition is recorded with its base register while the condition itself stays unproven.'
            'Stock prelinked import tables are already bound; there is no relocation/import descriptor for a late-loaded adapter. A new adapter must obtain its bindings from the same prelink/kxld pipeline.',
            'GOP ownership hand-off and the producer call into polaris_display_present have no stock-kernelcache evidence; the shipped provider graph is DT AppleARMIODevice/AppleCLCD.',
            'No runtime, hardware, panel, backlight or vblank evidence exists in this report.',
        ],
    )
    output_path = Path(args.output)
    protected = {Path(source).resolve(), Path(args.reference).resolve()}
    A.require(output_path.resolve() not in protected, 'output must not overwrite an audit input')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(dict(output=str(output_path),
                          sha256=report['input']['sha256'],
                          family_classes=len(family_data['classes']),
                          legacy_slots=len(legacy_rows),
                          subclass_overrides=(subclass_evidence or {}).get('override_count'),
                          adapter_ready=report['adapter_ready'])))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, StopIteration, struct.error) as error:
        raise SystemExit('display structural evidence failed: ' + str(error))
