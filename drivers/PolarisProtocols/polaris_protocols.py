"""Bounded host-side protocol cores for the Polaris SDM845 peripherals.

These codecs are deliberately transport independent.  They describe the
wire formats needed by a future Darwin 23 driver, but never access MMIO, SPMI,
I2C, UART, GPIO, DMA, firmware files, or IOKit.  A transport must validate the
board and ownership before it uses any result from this module.

The layouts are based on the local Polaris XNU/WOA research records and the
BSD-2-Clause-Patent UniXNU-sheng protocol references.  The exact transports
and firmware ownership remain unverified on a Darwin temporary boot.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence


class ProtocolError(ValueError):
    """The supplied record is malformed or outside the bounded contract."""


def _bytes(raw: Sequence[int], *, exact: int | None = None,
           maximum: int | None = None) -> bytes:
    try:
        values = tuple(int(value) for value in raw)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("record is not a byte sequence") from exc
    if exact is not None and len(values) != exact:
        raise ProtocolError(f"record must contain exactly {exact} bytes")
    if maximum is not None and len(values) > maximum:
        raise ProtocolError(f"record exceeds {maximum} bytes")
    if any(value < 0 or value > 0xFF for value in values):
        raise ProtocolError("record contains a value outside one byte")
    return bytes(values)


# ------------------------------ WCN3990 H4 ------------------------------


@dataclass(frozen=True)
class QcaVersion:
    product: int
    patch: int
    rom: int
    soc: int


def qca_version_request() -> bytes:
    """Return the H4 vendor version request used by WCN3990 research."""

    return bytes((0x01, 0x00, 0xFC, 0x01, 0x19))


def qca_segment_request(data: Sequence[int]) -> bytes:
    payload = _bytes(data, maximum=243)
    if not payload:
        raise ProtocolError("QCA firmware segment must not be empty")
    return bytes((0x01, 0x00, 0xFC, len(payload) + 2, 0x1E, len(payload))) + payload


def parse_qca_version_event(event: Sequence[int]) -> QcaVersion:
    raw = _bytes(event, exact=17)
    if raw[:5] != bytes((0x04, 0xFF, 0x0E, 0x00, 0x02)):
        raise ProtocolError("unexpected WCN3990 version event")
    product = int.from_bytes(raw[5:9], "little")
    patch = int.from_bytes(raw[9:11], "little")
    rom = int.from_bytes(raw[11:13], "little")
    soc = int.from_bytes(raw[13:17], "little")
    if rom == 0 or soc == 0:
        raise ProtocolError("WCN3990 version event has no ROM/SoC identity")
    return QcaVersion(product, patch, rom, soc)


class H4EventReader:
    """Incrementally assemble one bounded H4 event packet."""

    def __init__(self, maximum: int = 258) -> None:
        self.maximum = maximum
        self.reset()

    def reset(self) -> None:
        self._data = bytearray()
        self._expected: int | None = None

    def feed(self, value: int) -> bool:
        if value < 0 or value > 0xFF:
            raise ProtocolError("H4 byte is outside one byte")
        if not self._data and value != 0x04:
            self.reset()
            raise ProtocolError("unsupported H4 packet type")
        if len(self._data) >= self.maximum:
            self.reset()
            raise ProtocolError("H4 event exceeds the bounded packet size")
        self._data.append(value)
        if len(self._data) == 3:
            self._expected = self._data[2] + 3
            if self._expected > self.maximum:
                self.reset()
                raise ProtocolError("H4 event length exceeds the bounded packet size")
        return self._expected is not None and len(self._data) == self._expected

    @property
    def packet(self) -> bytes | None:
        if self._expected is None or len(self._data) != self._expected:
            return None
        return bytes(self._data)


# ------------------------------ WLFW QMI --------------------------------


WLFW_BDF_MESSAGE = 0x25
WLFW_CHUNK_BYTES = 6144


def wlfw_bdf_request(file_data: Sequence[int], segment: int) -> bytes:
    """Build the bounded QMI TLV body for one WCN3990 board-data chunk."""

    raw = _bytes(file_data)
    if not raw or segment < 0:
        raise ProtocolError("WLFW input and segment must be valid")
    offset = segment * WLFW_CHUNK_BYTES
    if offset >= len(raw):
        raise ProtocolError("WLFW segment is beyond the file")
    chunk = raw[offset:offset + WLFW_CHUNK_BYTES]
    final = int(offset + len(chunk) == len(raw))
    out = bytearray((0x01, 0x01, 0x00, 0x01))

    def tlv(tag: int, value: bytes) -> None:
        out.append(tag)
        out.extend(len(value).to_bytes(2, "little"))
        out.extend(value)

    tlv(0x10, (0).to_bytes(4, "little"))
    tlv(0x11, len(raw).to_bytes(4, "little"))
    tlv(0x12, segment.to_bytes(4, "little"))
    tlv(0x13, len(chunk).to_bytes(2, "little") + chunk)
    tlv(0x14, bytes((final,)))
    return bytes(out)


def wlfw_bdf_accepted(response: Sequence[int]) -> bool:
    raw = _bytes(response, exact=7)
    return raw == bytes((0x02, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00))


# -------------------------------- NCI -----------------------------------


@dataclass(frozen=True)
class NciPacket:
    packet_type: int
    group: int
    opcode: int
    payload: bytes


def parse_nci_control(data: Sequence[int]) -> NciPacket:
    raw = _bytes(data, maximum=258)
    if len(raw) < 3 or len(raw) != 3 + raw[2]:
        raise ProtocolError("NCI control packet length is inconsistent")
    packet_type = (raw[0] >> 5) & 0x07
    if raw[0] & 0x10 or not 1 <= packet_type <= 3:
        raise ProtocolError("NCI packet is fragmented or has an invalid type")
    if raw[1] & 0xC0:
        raise ProtocolError("NCI opcode contains reserved bits")
    return NciPacket(packet_type, raw[0] & 0x0F, raw[1] & 0x3F, raw[3:])


class NciHandshakeState(str, Enum):
    IDLE = "idle"
    AWAIT_RESET = "await-reset"
    SEND_INIT = "send-init"
    AWAIT_INIT = "await-init"
    READY = "ready"
    FAILED = "failed"


class NciCoreHandshake:
    """NCI 1.x CORE_RESET/CORE_INIT exchange with strict response checks."""

    def __init__(self) -> None:
        self.state = NciHandshakeState.IDLE

    def reset(self) -> None:
        self.state = NciHandshakeState.IDLE

    def timeout(self) -> None:
        if self.state is not NciHandshakeState.READY:
            self.state = NciHandshakeState.FAILED

    def next_command(self) -> bytes | None:
        if self.state is NciHandshakeState.IDLE:
            self.state = NciHandshakeState.AWAIT_RESET
            return bytes((0x20, 0x00, 0x01, 0x00))
        if self.state is NciHandshakeState.SEND_INIT:
            self.state = NciHandshakeState.AWAIT_INIT
            return bytes((0x20, 0x01, 0x00))
        return None

    def accept_response(self, data: Sequence[int]) -> bool:
        try:
            packet = parse_nci_control(data)
        except ProtocolError:
            self.state = NciHandshakeState.FAILED
            return False
        if self.state not in (NciHandshakeState.AWAIT_RESET,
                              NciHandshakeState.AWAIT_INIT):
            self.state = NciHandshakeState.FAILED
            return False
        if (packet.packet_type != 2 or packet.group != 0 or not packet.payload or
                packet.payload[0] != 0):
            self.state = NciHandshakeState.FAILED
            return False
        if self.state is NciHandshakeState.AWAIT_RESET:
            if packet.opcode != 0 or len(packet.payload) != 3 or packet.payload[1] >> 4 != 1:
                self.state = NciHandshakeState.FAILED
                return False
            self.state = NciHandshakeState.SEND_INIT
            return True
        if packet.opcode != 1 or len(packet.payload) < 17:
            self.state = NciHandshakeState.FAILED
            return False
        if len(packet.payload) != 17 + packet.payload[5]:
            self.state = NciHandshakeState.FAILED
            return False
        self.state = NciHandshakeState.READY
        return True


# -------------------------------- CCI -----------------------------------


@dataclass(frozen=True)
class CciReadRequest:
    register: int
    slave_address: int
    register_bytes: int
    read_bytes: int
    retries: int = 0


def encode_cci_read(request: CciReadRequest) -> tuple[int, ...]:
    if not 0 <= request.slave_address <= 0x7F:
        raise ProtocolError("CCI slave address must be seven bits")
    if not 1 <= request.register_bytes <= 3:
        raise ProtocolError("CCI register width must be one to three bytes")
    if not 1 <= request.read_bytes <= 12:
        raise ProtocolError("CCI read length must be one to twelve bytes")
    if not 0 <= request.retries <= 3:
        raise ProtocolError("CCI retry count must be zero to three")
    if request.register < 0 or request.register >> (request.register_bytes * 8):
        raise ProtocolError("CCI register does not fit its selected width")
    address_word = 11 | (request.register_bytes << 4)
    for index in range(request.register_bytes):
        address_word |= ((request.register >> (8 * index)) & 0xFF) << (8 * (request.register_bytes - index))
    return (
        1 | (request.slave_address << 4) | (request.retries << 16),
        6,
        address_word,
        10 | (request.read_bytes << 4),
        7,
    )


def decode_cci_read(words: Sequence[int], requested_bytes: int) -> bytes:
    if not 1 <= requested_bytes <= 12 or len(words) != requested_bytes // 4 + 1:
        raise ProtocolError("CCI FIFO length does not match the requested read")
    if any(value < 0 or value > 0xFFFFFFFF for value in words):
        raise ProtocolError("CCI FIFO word is outside 32 bits")
    result = bytearray()
    for index in range(requested_bytes):
        source = index + 1
        result.append((words[source // 4] >> (8 * (source % 4))) & 0xFF)
    return bytes(result)


# ---------------------------- PMIC / battery -----------------------------


class BatteryRevision(str, Enum):
    UNKNOWN = "unknown"
    EARLY = "early"
    V2 = "v2"


def identify_battery_revision(first: Sequence[int], second: Sequence[int]) -> BatteryRevision:
    a = _bytes(first, exact=3)
    b = _bytes(second, exact=3)
    if a != b or a[1:] != bytes((0x51, 0x15)):
        return BatteryRevision.UNKNOWN
    if a[0] == 1:
        return BatteryRevision.EARLY
    if a[0] == 2:
        return BatteryRevision.V2
    return BatteryRevision.UNKNOWN


def decode_battery_word(revision: BatteryRevision, byte0: int, byte1: int) -> int:
    if revision is BatteryRevision.EARLY:
        return (byte0 << 8) | byte1
    if revision is BatteryRevision.V2:
        return (byte1 << 8) | byte0
    raise ProtocolError("battery revision is unknown")


def conservative_soc_percent(raw: int) -> int:
    if not 0 <= raw <= 255:
        raise ProtocolError("battery SOC must be one byte")
    if raw == 0:
        return 0
    if raw == 255:
        return 100
    return (((raw - 1) * 98) + 126) // 253 + 1


@dataclass(frozen=True)
class FuelGaugeSample:
    percent: int
    millivolts: int
    current_microamps: int
    temperature_deci_celsius: int


def convert_fuel_gauge_sample(revision: BatteryRevision, soc: Sequence[int],
                              voltage: Sequence[int], current: Sequence[int],
                              temperature: Sequence[int]) -> FuelGaugeSample:
    if len(soc) != 1 or not all(len(pair) == 2 for pair in (voltage, current, temperature)):
        raise ProtocolError("fuel gauge sample has an invalid field length")
    if soc[0] < 0 or soc[0] > 255:
        raise ProtocolError("fuel gauge SOC is outside one byte")
    v = decode_battery_word(revision, voltage[0], voltage[1])
    i = decode_battery_word(revision, current[0], current[1])
    signed = i - 0x10000 if i & 0x8000 else i
    temp_raw = ((temperature[1] & 0x07) << 8) | temperature[0]
    return FuelGaugeSample(
        percent=conservative_soc_percent(soc[0]),
        millivolts=(v * 122070) // 1_000_000,
        current_microamps=(signed * 488281) // 1000,
        temperature_deci_celsius=(((temp_raw + 2) // 4) - 273) * 10,
    )


def permitted_spmi_read(peripheral: int, register: int, count: int) -> bool:
    """The narrow read-only SPMI whitelist used by the Polaris prototypes."""

    if not 1 <= count <= 8 or not 0 <= register <= 0xFF or register + count > 0x100:
        return False
    if peripheral == 0x008 and count == 1:
        return register in (0x04, 0x05, 0x10)
    if peripheral == 0x0C5 and count == 1:
        return register in (0x04, 0x05, 0x10, 0x40, 0x42, 0x46)
    if peripheral == 0x201:
        return register == 0x03 and count == 3
    if peripheral == 0x240:
        return (register == 0x05 and count == 1) or (register == 0x09 and count == 2)
    if peripheral == 0x241:
        return (register == 0x05 and count == 1) or (count == 2 and register in (0x50, 0xA0, 0xA2))
    return False


def spmi_read_command(register: int, count: int) -> int:
    if not permitted_spmi_read(0x008, register, count) and not permitted_spmi_read(0x0C5, register, count) and not permitted_spmi_read(0x201, register, count) and not permitted_spmi_read(0x240, register, count) and not permitted_spmi_read(0x241, register, count):
        raise ProtocolError("SPMI read is outside the board whitelist")
    return (1 << 27) | (register << 4) | (count - 1)


def decode_key_levels(pon_status: int, gpio_status: int) -> tuple[bool, bool, bool]:
    """Return (power, volume_up, volume_down) for the read-only PMIC levels."""

    if not 0 <= pon_status <= 0xFF or not 0 <= gpio_status <= 0xFF:
        raise ProtocolError("PMIC status must be one byte")
    # PON keys are active-high in the status register; GPIO6 volume-up is
    # active-low in the stock Polaris configuration.
    return bool(pon_status & 0x01), not bool(gpio_status & 0x01), bool(pon_status & 0x02)

