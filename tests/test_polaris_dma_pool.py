import importlib.util
import re
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("make_polaris_adt", ROOT / "scripts" / "make-polaris-adt.py")
ADT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADT)


def parse_tree(blob):
    """Return the ADT as {"name", "properties", "children"} with node names.

    UniXNU ADT layout: every node is u32 property_count, u32 child_count, then
    that many {name[32], length u32, value} records, then the child nodes.
    The node's own name is an ordinary property called "name".
    """
    def read_node(cursor):
        props, kids = struct.unpack_from("<II", blob, cursor)
        cursor += 8
        found = {}
        for _ in range(props):
            name = blob[cursor:cursor + 32].split(b"\0")[0].decode()
            length = struct.unpack_from("<I", blob, cursor + 32)[0]
            cursor += 36
            found[name] = blob[cursor:cursor + length]
            cursor = (cursor + length + 3) & ~3
        children = []
        for _ in range(kids):
            child, cursor = read_node(cursor)
            children.append(child)
        return {"name": found.get("name", b"").split(b"\0")[0].decode(),
                "properties": found, "children": children}, cursor

    root, _ = read_node(0)
    return root


def find_node(tree, name):
    if tree["name"] == name:
        return tree
    for child in tree["children"]:
        found = find_node(child, name)
        if found:
            return found
    return None


def find_node(tree, name):
    if name.encode() == tree["properties"].get("name", b"").split(b"\0")[0]:
        return tree
    for child in tree["children"]:
        found = find_node(child, name)
        if found:
            return found
    return None


class DmaPoolAdtTests(unittest.TestCase):
    def test_default_adt_requests_no_pool(self):
        blob = ADT.build()
        self.assertNotIn(b"darwinboot-dma-pool-size", blob)
        self.assertNotIn(b"darwinboot-dma-pool\0", blob)

    def test_requested_pool_emits_size_and_zeroed_slot(self):
        blob = ADT.build(dma_pool_size=0x40000)
        self.assertIn(b"darwinboot-dma-pool-size", blob)
        chosen = find_node(parse_tree(blob), "chosen")
        self.assertIsNotNone(chosen)
        size = chosen["properties"]["darwinboot-dma-pool-size"]
        slot = chosen["properties"]["darwinboot-dma-pool"]
        self.assertEqual(struct.unpack("<Q", size)[0], 0x40000)
        # The loader fills this in; a non-zero value would be a forged pool.
        self.assertEqual(slot, bytes(16))

    def test_pool_bounds_are_enforced(self):
        for bad in (0, 4096, 0x10000 - 1, 4 * 1024 * 1024 + 4096, 0x40001):
            with self.assertRaises(ValueError, msg=f"size {bad:#x} must be refused"):
                ADT.build(dma_pool_size=bad)

    def test_pool_size_must_be_page_aligned(self):
        with self.assertRaises(ValueError):
            ADT.build(dma_pool_size=0x40000 + 512)
        # The smallest accepted pool is one 4 KiB step above the minimum.
        blob = ADT.build(dma_pool_size=0x10000)
        self.assertIn(b"darwinboot-dma-pool-size", blob)

    def test_pool_stays_below_four_gib(self):
        with self.assertRaises(ValueError):
            ADT.build(dma_pool_size=0x100000000)


class DmaPoolHeaderTests(unittest.TestCase):
    """The C policy header must stay in step with the ADT and the driver."""

    @classmethod
    def setUpClass(cls):
        cls.header = (ROOT / "drivers" / "DarwinBoot" / "DarwinBootPkg" / "Driver" / "DmaPool.h").read_text()

    def test_header_ceiling_matches_the_adt_ceiling(self):
        self.assertIn("DARWIN_DMA_POOL_CEILING    0x100000000ULL", self.header)
        self.assertEqual(ADT.DMA_POOL_CEILING, 0x100000000)

    def test_header_bounds_match_the_adt_bounds(self):
        self.assertIn("DARWIN_DMA_POOL_MAX_BYTES  (4ULL * 1024ULL * 1024ULL)", self.header)
        self.assertIn("DARWIN_DMA_POOL_MIN_BYTES  (64ULL * 1024ULL)", self.header)
        self.assertEqual(ADT.DMA_POOL_MAX, 4 * 1024 * 1024)
        self.assertEqual(ADT.DMA_POOL_MIN, 64 * 1024)

    def test_pool_is_never_a_second_kernel_window(self):
        # A pool at or above the window would defeat the whole point.
        self.assertLess(ADT.DMA_POOL_MAX, 0x40000000)

    def test_darwinboot_refuses_rather_than_relocating(self):
        source = (ROOT / "drivers" / "DarwinBoot" / "DarwinBootPkg" / "Driver" / "DarwinBoot.c").read_text()
        self.assertIn("AllocateDmaPool", source)
        self.assertIn("low DMA pool unavailable; refusing to boot", source)
        # The pool must come from the boot services allocator, not a constant.
        self.assertRegex(source, r"AllocatePages \(AllocateAddress, EfiBootServicesData")
        # And the published slot must carry the real reservation.
        self.assertIn("WriteUnaligned64 ((UINT64 *)(UINTN)(TreeAddress + PoolSlotCandidate), DmaPool.Base)", source)

    def test_pool_properties_are_only_read_from_chosen(self):
        source = (ROOT / "drivers" / "DarwinBoot" / "DarwinBootPkg" / "Driver" / "DarwinBoot.c").read_text()
        # Both properties are length-checked where they are scanned.
        self.assertRegex(source, r"darwinboot-dma-pool-size[\s\S]{0,200}?Length != 8")
        self.assertRegex(source, r"darwinboot-dma-pool\"[\s\S]{0,200}?Length != 16")
        # And both are rejected outside /chosen and when seen twice.
        self.assertIn("(Path != 1) || (*PoolSizeOffset != MAX_UINTN)", source)
        self.assertIn("(Path != 1) || (*PoolSlotOffset != MAX_UINTN)", source)

    def test_pool_scan_locals_do_not_shadow_the_outputs(self):
        # A previous revision reused the output parameter names as locals, which
        # only the EDK2 build caught; keep the two namespaces separate.
        source = (ROOT / "drivers" / "DarwinBoot" / "DarwinBootPkg" / "Driver" / "DarwinBoot.c").read_text()
        self.assertIn("UINTN *PoolSizeOffset, UINTN *PoolSlotOffset", source)
        self.assertIn("UINTN  PoolCandidate;", source)
        self.assertIn("UINTN  PoolSlotCandidate;", source)


if __name__ == "__main__":
    unittest.main()
