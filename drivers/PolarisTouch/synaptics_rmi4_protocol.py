"""Host-side Synaptics RMI4 protocol reference for the Polaris touch work.

This module deliberately contains no I2C, GPIO, interrupt, MMIO, DMA, or
IOKit code. It models only the small RMI4/PDT and F12 frame pieces needed to
design a future Darwin 23 input service. The byte layout follows the checked-
in edk2-msm SynapticsRmi4Dxe reference:

* PDT entries are six bytes and are walked downward from 0xE9.
* The F12 single-contact sample used by that reference is eight bytes:
  status, little-endian X, little-endian Y, and three currently ignored bytes.

Neither the F12 layout nor the controller identity is claimed to have been
verified by a Darwin 23 temporary boot on Polaris.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence


PDT_ENTRY_BYTES = 6
PDT_DEFAULT_ADDRESS = 0xE9
PDT_MAX_FUNCTIONS = 10
F12_FUNCTION = 0x12
F12_FRAME_BYTES = 8
F12_ACTIVE_OBJECT_TYPE = 1


class Rmi4ProtocolError(ValueError):
    """The supplied bytes cannot be interpreted as a bounded RMI4 record."""


class F12FrameKind(str, Enum):
    ACTIVE = "active"
    RELEASE = "release"


@dataclass(frozen=True)
class Rmi4PdtEntry:
    query_base: int
    command_base: int
    control_base: int
    data_base: int
    interrupt_source_count: int
    function_number: int


@dataclass(frozen=True)
class F12Location:
    page: int
    pdt_address: int
    entry: Rmi4PdtEntry


@dataclass(frozen=True)
class F12Frame:
    status: int
    x: int
    y: int
    kind: F12FrameKind

    @property
    def contact(self) -> bool:
        return self.kind is F12FrameKind.ACTIVE


def _six_bytes(raw: Sequence[int]) -> tuple[int, ...]:
    try:
        values = tuple(int(value) for value in raw)
    except (TypeError, ValueError) as exc:
        raise Rmi4ProtocolError("PDT entry is not a byte sequence") from exc
    if len(values) != PDT_ENTRY_BYTES or any(value < 0 or value > 0xFF for value in values):
        raise Rmi4ProtocolError("PDT entry must contain exactly six bytes")
    return values


def parse_pdt_entry(raw: Sequence[int]) -> Rmi4PdtEntry:
    """Decode one six-byte RMI4 PDT entry, including the zero terminator."""

    query, command, control, data, interrupts, function = _six_bytes(raw)
    return Rmi4PdtEntry(query, command, control, data, interrupts, function)


def find_f12(pages: Iterable[Sequence[int]], *, pdt_address: int = PDT_DEFAULT_ADDRESS,
             max_functions: int = PDT_MAX_FUNCTIONS) -> F12Location:
    """Find an F12 descriptor in bounded 256-byte RMI4 page snapshots.

    ``pages`` are host-captured register pages, ordered by increasing RMI4
    page number. The function scans each page from ``pdt_address`` downward,
    stops at the zero-function terminator, and never reads beyond the supplied
    bytes. It performs no page switching; the returned page number is only a
    location for a future transport implementation.
    """

    if not 0 <= pdt_address <= 0xFF:
        raise Rmi4ProtocolError("PDT address must fit in an RMI4 page")
    if max_functions <= 0:
        raise Rmi4ProtocolError("max_functions must be positive")

    saw_page = False
    for page_number, page in enumerate(pages):
        saw_page = True
        try:
            page_bytes = tuple(int(value) for value in page)
        except (TypeError, ValueError) as exc:
            raise Rmi4ProtocolError("RMI4 page is not a byte sequence") from exc
        if len(page_bytes) > 256 or any(value < 0 or value > 0xFF for value in page_bytes):
            raise Rmi4ProtocolError("RMI4 page must contain at most 256 bytes")

        terminated = False
        for slot in range(max_functions):
            address = pdt_address - slot * PDT_ENTRY_BYTES
            if address < 0 or address + PDT_ENTRY_BYTES > len(page_bytes):
                raise Rmi4ProtocolError("PDT walk exceeds the supplied page")
            entry = parse_pdt_entry(page_bytes[address:address + PDT_ENTRY_BYTES])
            if entry.function_number == 0:
                terminated = True
                break
            if entry.function_number == F12_FUNCTION:
                return F12Location(page_number, address, entry)

        if not terminated:
            raise Rmi4ProtocolError("PDT page has no terminator within max_functions")

    if not saw_page:
        raise Rmi4ProtocolError("at least one RMI4 page is required")
    raise LookupError("RMI4 F12 function was not present in the supplied pages")


def parse_f12_frame(raw: Sequence[int], *, max_x: int | None = None,
                    max_y: int | None = None) -> F12Frame:
    """Decode the bounded eight-byte single-contact F12 sample.

    The low-nibble status is an object type: zero is a valid release and only
    object type one is accepted as an active contact until runtime evidence
    establishes another type. Optional inclusive coordinate limits reject
    impossible samples instead of silently handing them to a future HID layer.
    Bytes five through seven remain opaque because this reference intentionally
    models only the layout already present in the EDK2 implementation.
    """

    try:
        values = tuple(int(value) for value in raw)
    except (TypeError, ValueError) as exc:
        raise Rmi4ProtocolError("F12 frame is not a byte sequence") from exc
    if len(values) != F12_FRAME_BYTES or any(value < 0 or value > 0xFF for value in values):
        raise Rmi4ProtocolError("F12 frame must contain exactly eight bytes")
    if ((max_x is not None and max_x < 0) or
            (max_y is not None and max_y < 0)):
        raise Rmi4ProtocolError("coordinate limits must be non-negative")

    status = values[0] & 0x0F
    if status not in (0, F12_ACTIVE_OBJECT_TYPE):
        raise Rmi4ProtocolError("unsupported F12 object type")
    x = values[1] | (values[2] << 8)
    y = values[3] | (values[4] << 8)
    kind = F12FrameKind.ACTIVE if status != 0 else F12FrameKind.RELEASE
    if kind is F12FrameKind.ACTIVE:
        if max_x is not None and x > max_x:
            raise Rmi4ProtocolError("active F12 X coordinate exceeds the configured range")
        if max_y is not None and y > max_y:
            raise Rmi4ProtocolError("active F12 Y coordinate exceeds the configured range")
    return F12Frame(status=status, x=x, y=y, kind=kind)
