"""SCIP index reader: the subset that yields call edges.

Hand-rolled protobuf wire decoding, same reasoning as the MCP server:
`pip install tracekite-core` promises a light dependency set, and walking
varints for four fields does not justify a protobuf runtime. The walker
skips unknown fields by wire type, so schema growth in scip.proto never
breaks it — it can only miss NEW fields, never misread known ones.

Field numbers from scip.proto (sourcegraph/scip):
Index{metadata=1, documents=2}; Document{relative_path=1, occurrences=2};
Occurrence{range=1 packed, symbol=2, symbol_roles=3, enclosing_range=7
packed}. SymbolRole.Definition is bit 0x1. Ranges are 0-based
[startLine, startChar, endLine, endChar], 3 ints when one-line.
"""

from dataclasses import dataclass, field


@dataclass
class ScipOccurrence:
    range: list[int]
    symbol: str
    roles: int = 0
    enclosing: list[int] = field(default_factory=list)

    @property
    def is_definition(self) -> bool:
        return bool(self.roles & 0x1)

    @property
    def line(self) -> int:
        """1-based start line."""
        return (self.range[0] + 1) if self.range else 0


@dataclass
class ScipDocument:
    path: str
    occurrences: list[ScipOccurrence] = field(default_factory=list)


def _varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = data[pos]
        result |= (byte & 0x7F) << shift
        pos += 1
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint overflow")


def _fields(data: bytes):
    """Yield (field_number, wire_type, value) skipping what we don't know."""
    pos = 0
    while pos < len(data):
        tag, pos = _varint(data, pos)
        number, wire = tag >> 3, tag & 0x7
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 1:
            value, pos = data[pos:pos + 8], pos + 8
        elif wire == 2:
            length, pos = _varint(data, pos)
            value, pos = data[pos:pos + length], pos + length
        elif wire == 5:
            value, pos = data[pos:pos + 4], pos + 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        yield number, wire, value


def _packed_ints(data: bytes) -> list[int]:
    out, pos = [], 0
    while pos < len(data):
        value, pos = _varint(data, pos)
        out.append(value)
    return out


def _occurrence(data: bytes) -> ScipOccurrence:
    occ = ScipOccurrence(range=[], symbol="")
    for number, wire, value in _fields(data):
        if number == 1 and wire == 2:
            occ.range = _packed_ints(value)
        elif number == 2 and wire == 2:
            occ.symbol = value.decode("utf-8", errors="replace")
        elif number == 3 and wire == 0:
            occ.roles = value
        elif number == 7 and wire == 2:
            occ.enclosing = _packed_ints(value)
    return occ


def _document(data: bytes) -> ScipDocument:
    doc = ScipDocument(path="")
    for number, wire, value in _fields(data):
        if number == 1 and wire == 2:
            doc.path = value.decode("utf-8", errors="replace")
        elif number == 2 and wire == 2:
            doc.occurrences.append(_occurrence(value))
    return doc


def parse_scip(data: bytes) -> list[ScipDocument] | None:
    """Documents with occurrences, or None for bytes that are not SCIP."""
    try:
        docs = [_document(value) for number, wire, value in _fields(data)
                if number == 2 and wire == 2]
    except (ValueError, IndexError):
        return None
    docs = [d for d in docs if d.path]
    return docs or None
