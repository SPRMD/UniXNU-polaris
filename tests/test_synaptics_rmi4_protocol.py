import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "drivers" / "PolarisTouch" / "synaptics_rmi4_protocol.py"
spec = importlib.util.spec_from_file_location("synaptics_rmi4_protocol", MODULE_PATH)
protocol = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = protocol
assert spec.loader is not None
spec.loader.exec_module(protocol)


class SynapticsRmi4ProtocolTests(unittest.TestCase):
    def page(self):
        return bytearray(256)

    def put_entry(self, page, address, values):
        page[address:address + 6] = bytes(values)

    def test_pdt_entry_decodes_all_fields(self):
        entry = protocol.parse_pdt_entry((0x10, 0x20, 0x30, 0x40, 0x03, 0x12))
        self.assertEqual(entry.query_base, 0x10)
        self.assertEqual(entry.command_base, 0x20)
        self.assertEqual(entry.control_base, 0x30)
        self.assertEqual(entry.data_base, 0x40)
        self.assertEqual(entry.interrupt_source_count, 3)
        self.assertEqual(entry.function_number, 0x12)

    def test_f12_is_found_by_descending_pdt_walk(self):
        page = self.page()
        self.put_entry(page, 0xE9, (1, 2, 3, 4, 1, 0x01))
        self.put_entry(page, 0xE3, (5, 6, 7, 8, 2, 0x12))
        self.put_entry(page, 0xDD, (0, 0, 0, 0, 0, 0))
        found = protocol.find_f12((page,))
        self.assertEqual((found.page, found.pdt_address), (0, 0xE3))
        self.assertEqual(found.entry.data_base, 8)

    def test_f12_search_can_continue_to_the_next_page(self):
        first = self.page()
        second = self.page()
        self.put_entry(first, 0xE9, (1, 2, 3, 4, 1, 0x01))
        self.put_entry(first, 0xE3, (0, 0, 0, 0, 0, 0))
        self.put_entry(second, 0xE9, (9, 10, 11, 12, 1, 0x12))
        self.put_entry(second, 0xE3, (0, 0, 0, 0, 0, 0))
        found = protocol.find_f12((first, second))
        self.assertEqual((found.page, found.pdt_address), (1, 0xE9))

    def test_pdt_walk_rejects_missing_terminator(self):
        page = self.page()
        for slot in range(2):
            self.put_entry(page, 0xE9 - slot * 6, (1, 2, 3, 4, 0, 0x01))
        with self.assertRaises(protocol.Rmi4ProtocolError):
            protocol.find_f12((page,), max_functions=2)

    def test_f12_active_frame_uses_little_endian_coordinates(self):
        frame = protocol.parse_f12_frame(
            (1, 0x34, 0x12, 0x78, 0x56, 0, 0, 0), max_x=0x1234, max_y=0x5678
        )
        self.assertEqual(frame.status, 1)
        self.assertEqual((frame.x, frame.y), (0x1234, 0x5678))
        self.assertTrue(frame.contact)
        self.assertEqual(frame.kind, protocol.F12FrameKind.ACTIVE)

    def test_unknown_object_type_is_rejected(self):
        with self.assertRaises(protocol.Rmi4ProtocolError):
            protocol.parse_f12_frame((2, 0, 0, 0, 0, 0, 0, 0))

    def test_zero_status_is_a_valid_release(self):
        frame = protocol.parse_f12_frame((0, 0xFF, 0xFF, 0xFF, 0xFF, 0, 0, 0))
        self.assertFalse(frame.contact)
        self.assertEqual(frame.kind, protocol.F12FrameKind.RELEASE)

    def test_active_frame_bounds_and_length_are_fail_closed(self):
        with self.assertRaises(protocol.Rmi4ProtocolError):
            protocol.parse_f12_frame((1, 0x01, 0x02, 0, 0, 0, 0, 0), max_x=0x100)
        with self.assertRaises(protocol.Rmi4ProtocolError):
            protocol.parse_f12_frame((1, 2, 3))
        with self.assertRaises(protocol.Rmi4ProtocolError):
            protocol.parse_f12_frame((1, 0, 0, 0, 0, 0, 0, 0), max_x=-1)


if __name__ == "__main__":
    unittest.main()
