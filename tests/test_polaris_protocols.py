import unittest

from drivers.PolarisProtocols.polaris_protocols import (
    BatteryRevision,
    CciReadRequest,
    H4EventReader,
    NciCoreHandshake,
    NciHandshakeState,
    ProtocolError,
    decode_cci_read,
    decode_key_levels,
    identify_battery_revision,
    convert_fuel_gauge_sample,
    encode_cci_read,
    parse_nci_control,
    parse_qca_version_event,
    permitted_spmi_read,
    qca_segment_request,
    qca_version_request,
    h4_command,
    spmi_read_command,
    wlfw_bdf_accepted,
    wlfw_bdf_request,
)


class PolarisProtocolTests(unittest.TestCase):
    def test_qca_version_and_h4_reader(self):
        self.assertEqual(qca_version_request(), bytes((1, 0, 0xFC, 1, 0x19)))
        self.assertEqual(h4_command(0xFC00, (0x19,)),
                         bytes((1, 0, 0xFC, 1, 0x19)))
        event = bytes((4, 0xFF, 14, 0, 2)) + (0x12345678).to_bytes(4, "little")
        event += (0x3456).to_bytes(2, "little") + (0x789A).to_bytes(2, "little")
        event += (0xABCDEF01).to_bytes(4, "little")
        version = parse_qca_version_event(event)
        self.assertEqual((version.product, version.patch, version.rom, version.soc),
                         (0x12345678, 0x3456, 0x789A, 0xABCDEF01))
        reader = H4EventReader()
        self.assertFalse(reader.feed(4))
        self.assertFalse(reader.feed(0xFF))
        self.assertTrue(reader.feed(0))
        self.assertEqual(reader.packet, bytes((4, 0xFF, 0)))

    def test_qca_and_wlfw_bounds(self):
        self.assertEqual(len(qca_segment_request(bytes(243))), 249)
        with self.assertRaises(ProtocolError):
            qca_segment_request(bytes(244))
        with self.assertRaises(ProtocolError):
            h4_command(0x10000)
        with self.assertRaises(ProtocolError):
            h4_command(0xFC00, bytes(256))
        request = wlfw_bdf_request(bytes(range(32)), 0)
        self.assertEqual(request[:4], bytes((1, 1, 0, 1)))
        self.assertEqual(request[-4:], bytes((0x14, 1, 0, 1)))
        self.assertTrue(wlfw_bdf_accepted(bytes((2, 4, 0, 0, 0, 0, 0))))
        self.assertFalse(wlfw_bdf_accepted(bytes((2, 4, 0, 1, 0, 0, 0))))

    def test_nci_handshake(self):
        handshake = NciCoreHandshake()
        self.assertEqual(handshake.next_command(), bytes((0x20, 0, 1, 0)))
        reset_response = bytes((0x40, 0, 3, 0, 0x10, 0))
        self.assertTrue(handshake.accept_response(reset_response))
        self.assertEqual(handshake.state, NciHandshakeState.SEND_INIT)
        self.assertEqual(handshake.next_command(), bytes((0x20, 1, 0)))
        # The response length contract is 17 + the interface-list count;
        # this fixture advertises an empty interface list.
        payload = bytes(17)
        init_response = bytes((0x40, 1, len(payload))) + payload
        self.assertTrue(handshake.accept_response(init_response))
        self.assertEqual(handshake.state, NciHandshakeState.READY)
        self.assertEqual(parse_nci_control(init_response).opcode, 1)

    def test_cci_round_trip(self):
        request = CciReadRequest(0x1234, 0x20, 2, 4, 1)
        words = encode_cci_read(request)
        self.assertEqual(words[0], 1 | (0x20 << 4) | (1 << 16))
        fifo = (0x44332211, 0x000000AA)
        self.assertEqual(decode_cci_read(fifo, 4), bytes((0x22, 0x33, 0x44, 0xAA)))
        with self.assertRaises(ProtocolError):
            encode_cci_read(CciReadRequest(0x100, 0x20, 1, 1))

    def test_battery_and_spmi(self):
        self.assertEqual(identify_battery_revision((1, 0x51, 0x15), (1, 0x51, 0x15)), BatteryRevision.EARLY)
        self.assertEqual(identify_battery_revision((3, 0x51, 0x15), (3, 0x51, 0x15)), BatteryRevision.UNKNOWN)
        sample = convert_fuel_gauge_sample(
            BatteryRevision.V2, (128,), (0x34, 0x12), (0, 0), (0x40, 0x04)
        )
        self.assertEqual(sample.percent, 50)
        self.assertGreater(sample.millivolts, 0)
        self.assertEqual(decode_key_levels(0x03, 0x00), (True, True, True))
        self.assertTrue(permitted_spmi_read(0x240, 0x09, 2))
        self.assertFalse(permitted_spmi_read(0x240, 0x10, 1))
        self.assertGreater(spmi_read_command(0x10, 1), 0)
        with self.assertRaises(ProtocolError):
            spmi_read_command(0x20, 1)


if __name__ == "__main__":
    unittest.main()
