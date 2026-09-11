"""Protobuf and buf parsing.

`package.Service/Rpc` is the cleanest global key in the landscape: both sides of
a gRPC call emit it independently and identically, so unlike HTTP it needs no
service hint to join. That makes R5 the highest-precision cross-repo resolver
available.

A focused reader rather than a full protobuf grammar — the constructs that carry
identity (package, service, rpc, import, option) are unambiguous at the token
level, and a `.proto` that fails to compile still declares them.
"""

import logging
import re
from dataclasses import dataclass, field

import yaml
from evigraph.parsers.brace_blocks import balanced_block

logger = logging.getLogger(__name__)

_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_PACKAGE = re.compile(r"^\s*package\s+([A-Za-z_][\w.]*)\s*;", re.MULTILINE)
_IMPORT = re.compile(r'^\s*import\s+(?:public\s+|weak\s+)?"([^"]+)"\s*;', re.MULTILINE)
_OPTION = re.compile(r'^\s*option\s+([\w.()]+)\s*=\s*"?([^";]+)"?\s*;', re.MULTILINE)
_SERVICE = re.compile(r"\bservice\s+([A-Za-z_]\w*)\s*\{", re.MULTILINE)
_RPC = re.compile(
    r"\brpc\s+([A-Za-z_]\w*)\s*\(\s*(stream\s+)?([\w.]+)\s*\)\s*"
    r"returns\s*\(\s*(stream\s+)?([\w.]+)\s*\)")
_MESSAGE = re.compile(r"\bmessage\s+([A-Za-z_]\w*)\s*\{", re.MULTILINE)


@dataclass
class ProtoRpc:
    name: str
    input_type: str
    output_type: str
    client_streaming: bool = False
    server_streaming: bool = False
    line: int = 0
    # google.api.http binding: the proto ITSELF declaring that this rpc is
    # also served over HTTP. Authored equivalence, not an inference.
    http_method: str = ""
    http_path: str = ""

    @property
    def streaming(self) -> str:
        if self.client_streaming and self.server_streaming:
            return "bidi"
        if self.client_streaming:
            return "client"
        if self.server_streaming:
            return "server"
        return "unary"


@dataclass
class ProtoService:
    name: str
    package: str
    rpcs: list[ProtoRpc] = field(default_factory=list)
    line: int = 0

    @property
    def full_name(self) -> str:
        return f"{self.package}.{self.name}" if self.package else self.name

    def operation_keys(self) -> list[str]:
        """`package.Service/Rpc` — the wire-level method path gRPC itself uses."""
        return [f"{self.full_name}/{rpc.name}" for rpc in self.rpcs]


@dataclass
class ProtoFile:
    package: str = ""
    services: list[ProtoService] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    options: dict = field(default_factory=dict)
    file_path: str = ""

    @property
    def go_package(self) -> str:
        return str(self.options.get("go_package", ""))

    @property
    def java_package(self) -> str:
        return str(self.options.get("java_package", ""))


def _strip_comments(content: str) -> str:
    """Blank comments while preserving newlines, so line numbers stay right."""
    def blank(match: re.Match) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))
    return _COMMENT.sub(blank, content)


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1




def parse_proto(file_path: str, content: str) -> ProtoFile:
    """Parse one .proto file into its declared identity."""
    clean = _strip_comments(content)
    result = ProtoFile(file_path=file_path)

    if match := _PACKAGE.search(clean):
        result.package = match.group(1)
    result.imports = _IMPORT.findall(clean)
    for key, value in _OPTION.findall(clean):
        result.options[key.strip()] = value.strip().strip('"')
    result.messages = _MESSAGE.findall(clean)

    for match in _SERVICE.finditer(clean):
        body, _ = balanced_block(clean, clean.index("{", match.end() - 1))
        service = ProtoService(
            name=match.group(1), package=result.package,
            line=_line_of(clean, match.start()),
        )
        body_offset = clean.index("{", match.end() - 1) + 1
        for rpc_match in _RPC.finditer(body):
            rpc = ProtoRpc(
                name=rpc_match.group(1),
                input_type=rpc_match.group(3),
                output_type=rpc_match.group(5),
                client_streaming=bool(rpc_match.group(2)),
                server_streaming=bool(rpc_match.group(4)),
                line=_line_of(clean, body_offset + rpc_match.start()),
            )
            rpc.http_method, rpc.http_path = _http_binding(body,
                                                           rpc_match.end())
            service.rpcs.append(rpc)
        result.services.append(service)
    return result


_HTTP_VERB = re.compile(r'\b(get|put|post|delete|patch)\s*:\s*"([^"]+)"')


def _http_binding(body: str, rpc_end: int) -> tuple[str, str]:
    """The rpc's own `option (google.api.http)` verb and path, if declared."""
    brace = body.find("{", rpc_end)
    if brace == -1 or body[rpc_end:brace].strip() not in ("", ";"):
        return "", ""              # next brace belongs to something else
    block, _ = balanced_block(body, brace)
    if "google.api.http" not in block:
        return "", ""
    if match := _HTTP_VERB.search(block):
        return match.group(1).upper(), match.group(2)
    return "", ""


@dataclass
class BufConfig:
    """buf.yaml / buf.lock — declared cross-repo proto dependencies."""
    name: str = ""
    deps: list[str] = field(default_factory=list)
    file_path: str = ""


def parse_buf(file_path: str, content: str) -> BufConfig:
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return BufConfig(file_path=file_path)
    if not isinstance(data, dict):
        return BufConfig(file_path=file_path)

    config = BufConfig(name=str(data.get("name") or ""), file_path=file_path)
    for dep in data.get("deps") or []:
        if isinstance(dep, str):
            config.deps.append(dep)
        elif isinstance(dep, dict):
            # buf.lock entries: {remote, owner, repository, commit}
            parts = [str(dep.get(k) or "") for k in ("remote", "owner", "repository")]
            if all(parts):
                config.deps.append("/".join(parts))
    # buf.yaml v2 nests the module name under `modules:`
    for module in data.get("modules") or []:
        if isinstance(module, dict) and module.get("name") and not config.name:
            config.name = str(module["name"])
    return config


_THRIFT_NAMESPACE = re.compile(r"^namespace\s+(\w+)\s+([\w.]+)", re.MULTILINE)
_THRIFT_SERVICE = re.compile(r"\bservice\s+(\w+)(?:\s+extends\s+[\w.]+)?\s*\{")
_THRIFT_METHOD = re.compile(
    r"(?:oneway\s+)?([\w.<>, ]+?)\s+(\w+)\s*\(([^)]*)\)")


def parse_thrift(file_path: str, content: str) -> ProtoFile:
    """Thrift IDL services (carry-over).

    A thrift service declares operations exactly like a protobuf service, and
    thrift-generated Go/Python client classes already match the generic
    `New<X>Client` / `<X>Client` stub patterns — so reusing the proto shapes
    puts thrift on the same ContractOperation rendezvous with zero new linker
    code. The java namespace stands in for the proto package.
    """
    clean = _strip_comments(content)
    namespaces = dict(_THRIFT_NAMESPACE.findall(clean))
    package = namespaces.get("java") or namespaces.get("py") \
        or next(iter(namespaces.values()), "")
    proto = ProtoFile(package=package, file_path=file_path,
                      options={"protocol": "thrift"})

    for match in _THRIFT_SERVICE.finditer(clean):
        body, _ = balanced_block(clean, clean.index("{", match.end() - 1))
        service = ProtoService(name=match.group(1), package=package,
                               line=clean.count("\n", 0, match.start()) + 1)
        for method in _THRIFT_METHOD.finditer(body):
            return_type, name = method.group(1).strip(), method.group(2)
            if return_type in ("service", "struct", "enum", "exception"):
                continue
            service.rpcs.append(ProtoRpc(
                name=name, input_type=method.group(3).strip()[:80],
                output_type=return_type,
                line=service.line + body[:method.start()].count("\n") + 1,
            ))
        if service.rpcs:
            proto.services.append(service)
    return proto


def parse_wsdl(file_path: str, content: str) -> ProtoFile:
    """WSDL portType operations (carry-over, declaration side only).

    SOAP clients are generated in too many shapes to extract reliably, so a
    WSDL yields DECLARES_CONTRACT visibility — the operations exist in the
    graph even when no caller can be matched. Honest partial coverage.
    """
    import xml.etree.ElementTree as ET
    proto = ProtoFile(file_path=file_path, options={"protocol": "soap"})
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return proto

    def _local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    target_ns = root.get("targetNamespace", "")
    service_name = ""
    for element in root.iter():
        if _local(element.tag) == "service" and element.get("name"):
            service_name = element.get("name")
            break
    for element in root.iter():
        if _local(element.tag) != "portType":
            continue
        service = ProtoService(
            name=element.get("name") or service_name or "SoapService",
            package="",
        )
        for op in element:
            if _local(op.tag) == "operation" and op.get("name"):
                service.rpcs.append(ProtoRpc(name=op.get("name"),
                                             input_type="", output_type=""))
        if service.rpcs:
            proto.services.append(service)
    if target_ns:
        proto.options["target_namespace"] = target_ns
    return proto


def is_idl_file(file_name: str) -> str:
    """`thrift` | `wsdl` | '' — non-protobuf IDLs routed to their parsers."""
    if file_name.endswith(".thrift"):
        return "thrift"
    if file_name.endswith(".wsdl"):
        return "wsdl"
    return ""


def is_proto_file(file_name: str) -> bool:
    return file_name.endswith(".proto")


def is_buf_file(file_name: str) -> bool:
    return file_name in ("buf.yaml", "buf.yml", "buf.lock", "buf.work.yaml")
