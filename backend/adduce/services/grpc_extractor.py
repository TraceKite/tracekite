"""gRPC server implementations and client stub call sites.

The `.proto` file declares a contract; these locate who *implements* it and who
*calls* it. Both halves are needed — without client stubs every gRPC edge is
one-sided and answers no question.

Identity is the generated base/stub class name, which protoc derives from the
service name deterministically in every language (`OrdersServiceGrpc`,
`OrdersServiceBase`, `OrdersServiceClient`, `OrdersServiceStub`, ...). Matching
on that suffix pattern is what lets a Java server and a Go client meet without
either naming the other.
"""

import re
from dataclasses import dataclass

# Suffixes protoc appends to a service name; stripping one recovers the proto
# service name, which is the join key. Only the exact suffix protoc appends
# belongs here — compound forms like "ServiceClient" must not, because protoc
# generates <ServiceName>Client, so a service named OrdersService yields
# OrdersServiceClient and stripping "ServiceClient" leaves "Orders", which is a
# different service.
_SERVER_SUFFIXES = ("ImplBase", "Base", "Servicer", "Server")
_CLIENT_SUFFIXES = ("BlockingStub", "FutureStub", "Stub", "Client")

# --- servers ---------------------------------------------------------------

# JVM: @GrpcService on a class extending FooGrpc.FooImplBase
_JVM_GRPC_SERVICE = re.compile(r"@GrpcService\b")
# `extends OrdersServiceGrpc.OrdersServiceImplBase` -> OrdersService.
# The capture is greedy so it takes the whole name before the suffix; a lazy
# quantifier here matched a single character.
_JVM_EXTENDS_BASE = re.compile(
    r"\bextends\s+(?:[\w.]+\.)?(\w+)ImplBase\b"
    r"|\bextends\s+(?:[\w.]+\.)?(\w+)Grpc\b")
# C#: class OrdersService : Orders.OrdersBase
_CSHARP_BASE = re.compile(r":\s*(?:[\w.]*\.)?(\w+?)\.(\w+?)Base\b")
# Go: pb.RegisterOrdersServiceServer(s, &server{})
_GO_REGISTER = re.compile(r"\bRegister(\w+?)Server\s*\(")
# Python: add_OrdersServiceServicer_to_server / class X(pb2_grpc.OrdersServicer)
_PY_REGISTER = re.compile(r"\badd_(\w+?)Servicer_to_server\s*\(")
_PY_SERVICER = re.compile(r"class\s+\w+\s*\(\s*[\w.]*?(\w+?)Servicer\s*\)")
# Node: server.addService(ordersProto.OrdersService.service, impl)
_NODE_ADD_SERVICE = re.compile(
    r"\.addService\s*\(\s*[\w.]*?(\w+)\.service\b"
    r"|\.addService\s*\(\s*[\w.]*?(\w+)Service\b")

# --- clients ---------------------------------------------------------------

_JVM_NEW_STUB = re.compile(r"\b(\w+?)Grpc\s*\.\s*new(?:Blocking|Future)?Stub\s*\(")
_CSHARP_NEW_CLIENT = re.compile(r"\bnew\s+(?:[\w.]*\.)?(\w+?)\.(\w+?)Client\s*\(")
_GO_NEW_CLIENT = re.compile(r"\bNew(\w+?)Client\s*\(")
_PY_NEW_STUB = re.compile(r"\b(\w+?)Stub\s*\(")
_NODE_NEW_CLIENT = re.compile(
    r"\bnew\s+[\w.]*?(\w+?)Client\s*\("
    r"|\bnew\s+[\w.]*?(\w+)\s*\(\s*[^)]*credentials")


@dataclass
class GrpcSite:
    """One gRPC server implementation or client stub construction."""
    service_name: str          # proto service name, suffixes stripped
    role: str                  # provides | consumes
    line: int
    framework: str
    raw: str = ""


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


def strip_generated_suffix(name: str) -> str:
    """Recover the proto service name from a generated class name."""
    for suffix in sorted(_SERVER_SUFFIXES + _CLIENT_SUFFIXES, key=len, reverse=True):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    if name.endswith("Grpc") and len(name) > 4:
        return name[:-4]
    return name


def _add(sites: list[GrpcSite], content: str, pos: int, name: str, role: str,
         framework: str) -> None:
    service = strip_generated_suffix(name)
    if not service or len(service) < 2:
        return
    sites.append(GrpcSite(service_name=service, role=role, line=_line_of(content, pos),
                          framework=framework, raw=name))


def extract_grpc_sites(content: str, language: str | None) -> list[GrpcSite]:
    """gRPC server impls and client stubs in one file."""
    lang = (language or "").lower()
    sites: list[GrpcSite] = []

    if lang in ("java", "kotlin", "scala"):
        _jvm(content, sites)
    elif lang in ("c#", "csharp"):
        _csharp(content, sites)
    elif lang == "go":
        _go(content, sites)
    elif lang == "python":
        _python(content, sites)
    elif lang in ("javascript", "typescript"):
        _node(content, sites)

    # Same service claimed twice in a file (e.g. two stub constructions) is one
    # statement, not two.
    seen: set[tuple[str, str]] = set()
    unique: list[GrpcSite] = []
    for site in sites:
        key = (site.service_name, site.role)
        if key not in seen:
            seen.add(key)
            unique.append(site)
    return unique


def _jvm(content: str, sites: list[GrpcSite]) -> None:
    framework = "grpc-java"
    has_annotation = bool(_JVM_GRPC_SERVICE.search(content))
    for match in _JVM_EXTENDS_BASE.finditer(content):
        name = match.group(1) or match.group(2) or ""
        if name:
            _add(sites, content, match.start(), name, "provides",
                 "grpc-spring-boot" if has_annotation else framework)
    for match in _JVM_NEW_STUB.finditer(content):
        _add(sites, content, match.start(), match.group(1), "consumes", framework)


def _csharp(content: str, sites: list[GrpcSite]) -> None:
    framework = "grpc-dotnet"
    for match in _CSHARP_BASE.finditer(content):
        # `: Orders.OrdersBase` — the outer name is the proto service.
        _add(sites, content, match.start(), match.group(2) or match.group(1),
             "provides", framework)
    for match in _CSHARP_NEW_CLIENT.finditer(content):
        _add(sites, content, match.start(), match.group(2) or match.group(1),
             "consumes", framework)


def _go(content: str, sites: list[GrpcSite]) -> None:
    framework = "grpc-go"
    for match in _GO_REGISTER.finditer(content):
        _add(sites, content, match.start(), match.group(1), "provides", framework)
    for match in _GO_NEW_CLIENT.finditer(content):
        _add(sites, content, match.start(), match.group(1), "consumes", framework)


def _python(content: str, sites: list[GrpcSite]) -> None:
    framework = "grpcio"
    for pattern in (_PY_REGISTER, _PY_SERVICER):
        for match in pattern.finditer(content):
            _add(sites, content, match.start(), match.group(1), "provides", framework)
    for match in _PY_NEW_STUB.finditer(content):
        _add(sites, content, match.start(), match.group(1), "consumes", framework)


def _node(content: str, sites: list[GrpcSite]) -> None:
    framework = "grpc-js"
    for match in _NODE_ADD_SERVICE.finditer(content):
        name = match.group(1) or match.group(2) or ""
        if name:
            _add(sites, content, match.start(), name, "provides", framework)
    for match in _NODE_NEW_CLIENT.finditer(content):
        name = match.group(1) or match.group(2) or ""
        if name:
            _add(sites, content, match.start(), name, "consumes", framework)
