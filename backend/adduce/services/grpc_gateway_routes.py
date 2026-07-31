"""Routes served by generated grpc-gateway code (`*.pb.gw.go`).

A gRPC service exposed over HTTP through grpc-gateway registers its routes
in generated Go, and the path is never a literal there — it is a compiled
pattern:

    pattern_Camel_CaseService_GetStatus_0 = runtime.MustPattern(
        runtime.NewPattern(1, []int{2, 0, 2, 1, 1, 0, 4, 1, 5, 2},
                           []string{"v1", "camel_case", "state"}, ""))
    mux.Handle(http.MethodGet, pattern_Camel_CaseService_GetStatus_0, ...)

so a regex looking for a quoted path finds nothing. Before this, the whole
HTTP half of every grpc-gateway estate was invisible: the graph saw the
gRPC operations and none of the endpoints actually serving them, which is
why 104 `google.api.http` bindings in the reference corpus matched zero
contracts.

The ops list is grpc-gateway's own instruction encoding, paired
(opcode, operand), against the string pool:

    2 OpLitPush   a literal segment, pool[operand]
    1 OpPush      one wildcard segment
    3 OpPushM     the rest of the path (`**`)
    4 OpConcatN   concatenate the last N pushes — structural, no segment
    5 OpCapture   name the pushed segment pool[operand]

Decoding it is reading a declaration, not inferring one: the file states
exactly what it serves. A pattern that uses an opcode not listed here
yields nothing rather than a guess, because a path assembled from a
half-understood encoding would be a fabricated endpoint.
"""

import re

from adduce.services.go_route_extractor import GoRoute

_PATTERN_DEF = re.compile(
    r"pattern_(?P<name>[A-Za-z0-9_]+)\s*=\s*runtime\.MustPattern\(\s*"
    r"runtime\.NewPattern\(\s*\d+\s*,\s*\[\]int\{(?P<ops>[^}]*)\}\s*,\s*"
    r"\[\]string\{(?P<pool>[^}]*)\}\s*,\s*\"(?P<verb>[^\"]*)\"")

_HANDLE = re.compile(
    r"mux\.Handle\(\s*(?:http\.Method(?P<verb>[A-Z][a-z]+)|\"(?P<literal>[A-Z]+)\")"
    r"\s*,\s*pattern_(?P<name>[A-Za-z0-9_]+)")

_STRING = re.compile(r'"([^"]*)"')

# Opcodes that contribute to a path. OpConcatN is structural.
_LIT_PUSH, _PUSH, _PUSH_M, _CONCAT_N, _CAPTURE = 2, 1, 3, 4, 5
_KNOWN_OPS = {_LIT_PUSH, _PUSH, _PUSH_M, _CONCAT_N, _CAPTURE, 0}


def decode_pattern(ops: list[int], pool: list[str]) -> str | None:
    """The path template a compiled grpc-gateway pattern serves.

    Returns None when the encoding contains an opcode this decoder does not
    model, or references a pool entry that is not there — an endpoint
    invented from a misread instruction stream would be worse than a
    missing one.
    """
    if len(ops) % 2:
        return None
    segments: list[str] = []
    pending = 0                      # wildcard segments awaiting a name
    for opcode, operand in zip(ops[::2], ops[1::2]):
        if opcode not in _KNOWN_OPS:
            return None
        if opcode == _LIT_PUSH:
            if not 0 <= operand < len(pool):
                return None
            segments.append(pool[operand])
        elif opcode in (_PUSH, _PUSH_M):
            pending += 1
        elif opcode == _CAPTURE:
            if not 0 <= operand < len(pool):
                return None
            # One capture names everything pushed since the last segment.
            segments.append("{" + pool[operand] + "}")
            pending = 0
    segments.extend(["{}"] * pending)   # pushed but never named
    if not segments:
        return None
    return "/" + "/".join(segments)


def _ints(text: str) -> list[int] | None:
    try:
        return [int(part.strip()) for part in text.split(",") if part.strip()]
    except ValueError:
        return None


def _operation(pattern_name: str) -> tuple[str, str]:
    """`UnannotatedEchoService_Echo_1` -> ("UnannotatedEchoService", "Echo").

    The trailing index distinguishes several bindings on one rpc; the rpc
    itself is what the operation joins on, so it is kept and the index is
    dropped. Service names may themselves contain underscores
    (`Camel_CaseService`), so the split is anchored from the right.
    """
    parts = pattern_name.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        pattern_name = parts[0]
    service, _, rpc = pattern_name.rpartition("_")
    return service, rpc


def extract_gateway_routes(path: str, content: str) -> list[GoRoute]:
    """Every route a generated gateway registers, with its declared path."""
    if not path.endswith(".pb.gw.go"):
        return []

    templates: dict[str, str] = {}
    for match in _PATTERN_DEF.finditer(content):
        ops = _ints(match.group("ops"))
        if ops is None:
            continue
        pool = _STRING.findall(match.group("pool"))
        template = decode_pattern(ops, pool)
        if template is None:
            continue
        verb = match.group("verb")
        # A pattern verb is grpc-gateway's `:action` suffix, part of the path.
        templates[match.group("name")] = (
            f"{template}:{verb}" if verb else template)

    routes: list[GoRoute] = []
    for match in _HANDLE.finditer(content):
        name = match.group("name")
        template = templates.get(name)
        if template is None:
            continue                      # registered a pattern we cannot read
        method = (match.group("verb") or match.group("literal") or "").upper()
        if not method:
            continue
        service, rpc = _operation(name)
        routes.append(GoRoute(
            method=method, path=template, framework="grpc-gateway",
            line=content.count("\n", 0, match.start()) + 1,
            handler_name=f"{service}/{rpc}" if service and rpc else "",
            attrs={"grpc_service": service, "grpc_rpc": rpc,
                   "generated": True},
        ))
    return routes
