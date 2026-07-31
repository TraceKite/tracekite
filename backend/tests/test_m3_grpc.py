"""M3 gRPC: .proto -> claims -> R5 -> cross-repo operation edges.

`package.Service/Rpc` is globally unique by construction, so unlike HTTP a
match needs no service hint — that is what makes R5 the highest precision
cross-repo resolver available.
"""

from types import SimpleNamespace

import pytest

from adduce.parsers.proto_parser import parse_buf, parse_proto, parse_thrift
from adduce.services.grpc_extractor import extract_grpc_sites, strip_generated_suffix
from adduce.services.ingest_claims import (
    emit_grpc_site_claims, emit_proto_claims, emit_buf_claims,
)
from adduce.services.ingest_source import IngestSink
from adduce.services.linker import r0_alias, r2_k8s, r5_grpc
from adduce.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput, load_confidence,
)
from adduce.services.linker.engine import materialize_pending

PROTO = """
syntax = "proto3";

package petclinic.orders.v1;

option go_package = "github.com/myorg/orders/gen/ordersv1";
option java_package = "org.petclinic.orders.v1";

import "google/protobuf/timestamp.proto";

message GetOrderRequest { string id = 1; }
message Order { string id = 1; }

// The orders service.
service OrdersService {
  rpc GetOrder(GetOrderRequest) returns (Order);
  rpc ListOrders(ListRequest) returns (stream Order);
  rpc Sync(stream Order) returns (stream Order);
}

service AdminService {
  rpc Purge(PurgeRequest) returns (PurgeReply);
}
"""


def _file(path, language="proto"):
    return SimpleNamespace(path=path, language=language)


def _claims(sink, repo_id):
    records = []
    for node in sink.nodes:
        if node.type != "ContractClaim":
            continue
        extra = node.extra_props
        records.append(ClaimRecord(
            id=node.id, repo_id=repo_id, kind=extra["kind"],
            direction=extra["direction"], key=extra["key"],
            service_hint=extra.get("service_hint"),
            hint_source=extra.get("hint_source", "none"),
            matchable=bool(extra.get("matchable", True)),
            evidence=list(extra.get("evidence") or []),
            attrs=dict(node.metadata or {}),
            evidence_node_id=f"node:{node.id}", evidence_node_type="File",
        ))
    return records


def run_linker(claims):
    ctx = LinkContext("linkrun_test", load_confidence(), {})
    ctx.known_repos = {c.repo_id for c in claims}
    index = ClaimIndex(claims)
    out = ResolverOutput()
    for module in (r2_k8s, r0_alias, r5_grpc):
        out.extend(module.resolve(index, ctx))
    out.edges.extend(materialize_pending(ctx))
    return ctx, out


class TestProtoParser:
    def test_package_and_options(self):
        proto = parse_proto("orders.proto", PROTO)
        assert proto.package == "petclinic.orders.v1"
        assert proto.go_package == "github.com/myorg/orders/gen/ordersv1"
        assert proto.java_package == "org.petclinic.orders.v1"
        assert "google/protobuf/timestamp.proto" in proto.imports

    def test_services_and_rpcs(self):
        proto = parse_proto("orders.proto", PROTO)
        assert [s.name for s in proto.services] == ["OrdersService", "AdminService"]
        orders = proto.services[0]
        assert orders.full_name == "petclinic.orders.v1.OrdersService"
        assert [r.name for r in orders.rpcs] == ["GetOrder", "ListOrders", "Sync"]

    def test_operation_keys_are_the_wire_paths(self):
        [orders, _admin] = parse_proto("orders.proto", PROTO).services
        assert orders.operation_keys() == [
            "petclinic.orders.v1.OrdersService/GetOrder",
            "petclinic.orders.v1.OrdersService/ListOrders",
            "petclinic.orders.v1.OrdersService/Sync",
        ]

    def test_streaming_classification(self):
        rpcs = {r.name: r.streaming for r in parse_proto("o.proto", PROTO).services[0].rpcs}
        assert rpcs == {"GetOrder": "unary", "ListOrders": "server", "Sync": "bidi"}

    def test_messages_and_types(self):
        proto = parse_proto("orders.proto", PROTO)
        assert "GetOrderRequest" in proto.messages
        assert proto.services[0].rpcs[0].input_type == "GetOrderRequest"
        assert proto.services[0].rpcs[0].output_type == "Order"

    def test_comments_do_not_shift_line_numbers(self):
        proto = parse_proto("orders.proto", PROTO)
        line = proto.services[0].rpcs[0].line
        assert PROTO.split("\n")[line - 1].strip().startswith("rpc GetOrder")

    def test_commented_out_service_is_ignored(self):
        proto = parse_proto("x.proto", """
package p;
// service GhostService { rpc Nope(A) returns (B); }
/* service BlockGhost { rpc Nope(A) returns (B); } */
service RealService { rpc Yes(A) returns (B); }
""")
        assert [s.name for s in proto.services] == ["RealService"]

    def test_no_package_still_yields_keys(self):
        proto = parse_proto("x.proto", "service S { rpc R(A) returns (B); }")
        assert proto.services[0].operation_keys() == ["S/R"]

    def test_malformed_proto_does_not_raise(self):
        assert parse_proto("x.proto", "service Broken {").services[0].rpcs == []
        assert parse_proto("x.proto", "").services == []


THRIFT = """
namespace java org.petclinic.orders
namespace py petclinic.orders

service OrderService {
  Order getOrder(1: string id)
  void cancelOrder(1: string id)
}
"""


class TestThrift:
    """Thrift rides the proto shapes, and nothing exercised that path.

    `parse_thrift` called a helper that no longer existed — `_body_at` was
    proto's and graphql's old brace scanner, unified into `balanced_block`,
    and this one call site was missed. Every `.thrift` file with a service
    in it raised NameError from `parser_registry`, which is a crash on
    real input rather than the decline the parser contract requires.
    """

    def test_a_service_yields_its_operations(self):
        thrift = parse_thrift("orders.thrift", THRIFT)
        assert [s.name for s in thrift.services] == ["OrderService"]
        assert [r.name for r in thrift.services[0].rpcs] == [
            "getOrder", "cancelOrder"]

    def test_the_java_namespace_stands_in_for_the_package(self):
        thrift = parse_thrift("orders.thrift", THRIFT)
        assert thrift.package == "org.petclinic.orders"
        assert thrift.services[0].operation_keys() == [
            "org.petclinic.orders.OrderService/getOrder",
            "org.petclinic.orders.OrderService/cancelOrder"]

    def test_malformed_thrift_declines_instead_of_raising(self):
        assert parse_thrift("x.thrift", "service Broken {").services == []
        assert parse_thrift("x.thrift", "").services == []


class TestBuf:
    def test_module_name_and_deps(self):
        config = parse_buf("buf.yaml", """
version: v1
name: buf.build/myorg/orders
deps:
  - buf.build/googleapis/googleapis
""")
        assert config.name == "buf.build/myorg/orders"
        assert config.deps == ["buf.build/googleapis/googleapis"]

    def test_buf_lock_structured_deps(self):
        config = parse_buf("buf.lock", """
version: v1
deps:
  - remote: buf.build
    owner: myorg
    repository: common
    commit: abc123
""")
        assert config.deps == ["buf.build/myorg/common"]

    def test_malformed_buf_does_not_raise(self):
        assert parse_buf("buf.yaml", "bad: [").deps == []


class TestGrpcExtractor:
    def test_strip_generated_suffixes(self):
        for generated, expected in [
            ("OrdersServiceImplBase", "OrdersService"),
            ("OrdersServiceBlockingStub", "OrdersService"),
            ("OrdersServiceClient", "OrdersService"),
            ("OrdersServiceServicer", "OrdersService"),
            ("OrdersServiceGrpc", "OrdersService"),
        ]:
            assert strip_generated_suffix(generated) == expected

    def test_jvm_server_and_client(self):
        sites = extract_grpc_sites("""
@GrpcService
public class OrdersServiceImpl extends OrdersServiceGrpc.OrdersServiceImplBase {
}
""", "java")
        assert [(s.service_name, s.role) for s in sites] == [
            ("OrdersService", "provides")]
        assert sites[0].framework == "grpc-spring-boot"

        client = extract_grpc_sites(
            "var stub = OrdersServiceGrpc.newBlockingStub(channel);", "java")
        assert [(s.service_name, s.role) for s in client] == [
            ("OrdersService", "consumes")]

    def test_csharp_server_and_client(self):
        server = extract_grpc_sites(
            "public class OrdersService : Orders.OrdersBase { }", "c#")
        assert [(s.service_name, s.role) for s in server] == [
            ("Orders", "provides")]
        client = extract_grpc_sites(
            "var c = new Orders.OrdersClient(channel);", "csharp")
        assert [(s.service_name, s.role) for s in client] == [
            ("Orders", "consumes")]

    def test_go_server_and_client(self):
        sites = extract_grpc_sites("""
pb.RegisterOrdersServiceServer(s, &server{})
client := pb.NewOrdersServiceClient(conn)
""", "go")
        assert sorted((s.service_name, s.role) for s in sites) == [
            ("OrdersService", "consumes"), ("OrdersService", "provides")]

    def test_python_server_and_client(self):
        sites = extract_grpc_sites("""
orders_pb2_grpc.add_OrdersServiceServicer_to_server(Impl(), server)
stub = orders_pb2_grpc.OrdersServiceStub(channel)
""", "python")
        assert sorted((s.service_name, s.role) for s in sites) == [
            ("OrdersService", "consumes"), ("OrdersService", "provides")]

    def test_node_client(self):
        sites = extract_grpc_sites(
            "const c = new OrdersServiceClient(addr, credentials.createInsecure());",
            "typescript")
        assert ("OrdersService", "consumes") in [(s.service_name, s.role) for s in sites]

    def test_unsupported_language_yields_nothing(self):
        assert extract_grpc_sites("RegisterOrdersServiceServer(s)", "ruby") == []

    def test_repeated_stub_construction_is_one_statement(self):
        sites = extract_grpc_sites("""
a := pb.NewOrdersServiceClient(conn)
b := pb.NewOrdersServiceClient(conn2)
""", "go")
        assert len(sites) == 1


class TestR5Linking:
    """The payoff: a Go client and a Java server meet without naming each other."""

    def _estate(self):
        sink = IngestSink()
        emit_proto_claims("repo_contracts", _file("proto/orders.proto"),
                          parse_proto("proto/orders.proto", PROTO),
                          "file:proto", sink)
        server = IngestSink()
        emit_grpc_site_claims(
            "repo_orders", _file("src/main/java/OrdersImpl.java", "java"),
            "@GrpcService\npublic class OrdersImpl extends "
            "OrdersServiceGrpc.OrdersServiceImplBase {}",
            "file:server", server)
        client = IngestSink()
        emit_grpc_site_claims(
            "repo_web", _file("internal/client/orders.go", "go"),
            "client := pb.NewOrdersServiceClient(conn)",
            "file:client", client)
        return (_claims(sink, "repo_contracts") + _claims(server, "repo_orders")
                + _claims(client, "repo_web"))

    def test_proto_yields_one_operation_per_rpc(self):
        ctx, out = run_linker(self._estate())
        operations = {r.node_id for r in out.rendezvous
                      if r.label == "ContractOperation"}
        assert "global:Op:grpc:petclinic.orders.v1.OrdersService/GetOrder" in operations
        assert ctx.counters["r5.operations"] == 4

    def test_server_exposes_every_rpc_of_its_service(self):
        ctx, out = run_linker(self._estate())
        exposes = [e for e in out.edges if e.type == "EXPOSES"]
        assert len(exposes) == 3          # OrdersService has three rpcs
        assert ctx.counters["r5.server_matched"] == 1

    def test_client_invokes_across_repos(self):
        ctx, out = run_linker(self._estate())
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert len(invokes) == 3
        assert all(e.source_repo_id == "repo_web" for e in invokes)
        assert all(e.target_repo_id == "repo_contracts" for e in invokes)
        assert all(e.cross_repo for e in invokes)

    def test_service_name_only_match_scores_below_qualified(self):
        ctx, out = run_linker(self._estate())
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        # The stub knows `OrdersService`, not the package, so this is the
        # service_name tier rather than the exact tier.
        assert invokes[0].match_type == "grpc_service_name"
        assert invokes[0].confidence == pytest.approx(0.9)

    def test_proto_declaration_is_highest_confidence(self):
        _, out = run_linker(self._estate())
        declares = [e for e in out.edges if e.type == "DECLARES_CONTRACT"]
        assert declares and declares[0].confidence == pytest.approx(0.98)

    def test_unmatched_stub_is_counted_not_invented(self):
        sink = IngestSink()
        emit_grpc_site_claims(
            "repo_web", _file("c.go", "go"),
            "client := pb.NewUnknownServiceClient(conn)", "f", sink)
        ctx, out = run_linker(_claims(sink, "repo_web"))
        assert ctx.counters["r5.unmatched_client"] == 1
        assert not [e for e in out.edges if e.type == "INVOKES"]

    def test_test_file_stubs_do_not_link(self):
        # A stub built in a test is not a production dependency.
        sink = IngestSink()
        emit_proto_claims("repo_contracts", _file("proto/orders.proto"),
                          parse_proto("proto/orders.proto", PROTO),
                          "file:proto", sink)
        tests = IngestSink()
        emit_grpc_site_claims(
            "repo_web", _file("src/test/java/OrdersClientTest.java", "java"),
            "var stub = OrdersServiceGrpc.newBlockingStub(channel);",
            "f", tests, provenance="test")
        ctx, out = run_linker(_claims(sink, "repo_contracts")
                              + _claims(tests, "repo_web"))
        assert not [e for e in out.edges if e.type == "INVOKES"]
