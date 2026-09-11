"""C3: a SCIP index ingested during scan yields symbol-level CALLS.

The index is encoded here with a purpose-built encoder over the same
field numbers the parser documents — a round-trip against scip.proto's
published schema (Index.documents=2; Document.relative_path=1,
occurrences=2; Occurrence.range=1, symbol=2, symbol_roles=3,
enclosing_range=7). The anchoring rule carries the precision burden: an
edge lands only when both symbols match scanned entities by file,
containment and name, so a stale index cannot assert calls into
functions that no longer exist.
"""

import os

from tracekite import engine_config
from tracekite.parsers.scip_parser import parse_scip
from tracekite.services.scan import scan

SYM = "scip-python python demo 1 app/{}()."


def _varint(value: int) -> bytes:
    out = b""
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out += bytes([byte | 0x80])
        else:
            return out + bytes([byte])


def _field(number: int, payload: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(payload)) + payload


def _packed(number: int, values: list[int]) -> bytes:
    return _field(number, b"".join(_varint(v) for v in values))


def occurrence(rng, symbol, roles=0, enclosing=None) -> bytes:
    payload = _packed(1, rng) + _field(2, symbol.encode())
    if roles:
        payload += _varint(3 << 3) + _varint(roles)
    if enclosing:
        payload += _packed(7, enclosing)
    return payload


def document(path: str, occurrences: list[bytes]) -> bytes:
    payload = _field(1, path.encode())
    for occ in occurrences:
        payload += _field(2, occ)
    return payload


def index(documents: list[bytes]) -> bytes:
    return b"".join(_field(2, doc) for doc in documents)


CODE = "def helper():\n    return 1\n\n\ndef main():\n    return helper()\n"

INDEX = index([document("app.py", [
    occurrence([0, 4, 10], SYM.format("helper"), roles=1,
               enclosing=[0, 0, 1, 12]),
    occurrence([4, 4, 8], SYM.format("main"), roles=1,
               enclosing=[4, 0, 5, 19]),
    occurrence([5, 11, 17], SYM.format("helper")),
])])


def repo(tmp_path, index_bytes=INDEX):
    (tmp_path / "app.py").write_text(CODE)
    if index_bytes is not None:
        (tmp_path / "index.scip").write_bytes(index_bytes)
    engine_config.configure(graph_hmac_key="scip-test")
    return scan(str(tmp_path), "demo")


def scip_edges(sink):
    return [e for e in sink.edges
            if e.type == "CALLS" and e.detected_by == "scip_import"]


class TestParser:
    def test_round_trips_documents_and_occurrences(self):
        [doc] = parse_scip(INDEX)
        assert doc.path == "app.py"
        assert len(doc.occurrences) == 3
        definition = doc.occurrences[0]
        assert definition.is_definition and definition.line == 1
        assert definition.enclosing == [0, 0, 1, 12]

    def test_unknown_fields_are_skipped_not_fatal(self):
        # A future scip.proto field must never break the reader.
        extra = _field(9, b"future") + INDEX
        assert parse_scip(extra) is not None

    def test_garbage_is_none_never_a_raise(self):
        assert parse_scip(b"\xff\xff\xff not scip") is None


class TestScanIngestsTheIndex:
    def test_call_edge_present_with_scip_provenance(self, tmp_path):
        sink = repo(tmp_path)
        [edge] = scip_edges(sink)
        assert edge.match_type == "scip_reference"
        assert edge.evidence == ["app.py:6"]
        source = next(n for n in sink.nodes if n.id == edge.source_id)
        target = next(n for n in sink.nodes if n.id == edge.target_id)
        assert (source.name, target.name) == ("main", "helper")
        assert sink.claims.get("_scip_call") == 1
        # The heuristic resolver saw the same pair and deferred: one edge.
        calls = [e for e in sink.edges if e.type == "CALLS"
                 and (e.source_id, e.target_id) ==
                 (edge.source_id, edge.target_id)]
        assert len(calls) == 1

    def test_confidence_comes_from_config_not_a_literal(self, tmp_path):
        from tracekite.services.linker.base import load_confidence
        sink = repo(tmp_path)
        [edge] = scip_edges(sink)
        tier = load_confidence()["resolvers"]["scip_import"]["reference"]
        assert edge.confidence == tier["confidence"]

    def test_stale_symbol_is_counted_never_anchored(self, tmp_path):
        stale = index([document("app.py", [
            occurrence([0, 4, 10], SYM.format("helper"), roles=1,
                       enclosing=[0, 0, 1, 12]),
            occurrence([20, 4, 8], SYM.format("removed"), roles=1,
                       enclosing=[20, 0, 25, 10]),
            occurrence([21, 11, 17], SYM.format("helper")),
        ])])
        sink = repo(tmp_path, index_bytes=stale)
        assert scip_edges(sink) == []
        assert sink.claims.get("_scip_unanchored", 0) >= 1

    def test_unreadable_index_counts_and_scan_survives(self, tmp_path):
        sink = repo(tmp_path, index_bytes=b"\xff\xffgarbage")
        assert sink.claims.get("_scip_unreadable") == 1
        # The rest of the scan is untouched by the bad index.
        assert any(n.name == "helper" for n in sink.nodes)

    def test_no_index_no_change(self, tmp_path):
        sink = repo(tmp_path, index_bytes=None)
        assert scip_edges(sink) == []
        assert "_scip_call" not in sink.claims
