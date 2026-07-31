"""C7 exit criterion: one logical operation, three transports.

From authored sources: a .proto whose rpc declares its own HTTP binding
(google.api.http) and an Avro subject whose record is the rpc's
qualified output. The ContractOperation node ends up carrying
SAME_OPERATION edges to the HttpContract and the Topic — gRPC, HTTP and
Kafka, one operation. Everything less than authored declares nothing.
"""

from adduce.parsers.proto_parser import parse_proto
from adduce.services.calibration_estates import operation_estate
from adduce.services.linker.engine import link

PROTO = """
syntax = "proto3";
package demo.owners;

import "google/api/annotations.proto";

service OwnerService {
  rpc GetOwner(GetOwnerRequest) returns (OwnerEvent) {
    option (google.api.http) = {
      get: "/v1/owners/{id}"
    };
  }
  rpc DropOwner(DropOwnerRequest) returns (OwnerEvent);
}
"""


class TestProtoBindings:
    def test_the_protos_own_binding_is_extracted(self):
        [service] = parse_proto("owners.proto", PROTO).services
        bound, unbound = service.rpcs
        assert (bound.http_method, bound.http_path) == \
            ("GET", "/v1/owners/{id}")
        assert (unbound.http_method, unbound.http_path) == ("", "")

    def test_an_option_outside_the_rpc_body_binds_nothing(self):
        text = PROTO.replace("option (google.api.http)", "option (other)")
        [service] = parse_proto("owners.proto", text).services
        assert service.rpcs[0].http_method == ""


class TestOneOperationThreeTransports:
    def test_the_operation_reaches_all_three(self):
        estate = operation_estate()
        result = link(estate.claims, now="2026-01-01T00:00:00+00:00",
                      aliases={}, promotions=[])
        operation = "global:Op:grpc:demo.owners.OwnerService/GetOwner"
        same_op = {e.target_id: e for e in result.edges
                   if e.type == "SAME_OPERATION" and e.source_id == operation}
        assert set(same_op) == {
            "global:Http:repo_owners:GET:/v1/owners/{id}",
            "global:Topic:kafka:owners"}
        http_edge = same_op["global:Http:repo_owners:GET:/v1/owners/{id}"]
        assert http_edge.evidence == ["proto/owners.proto:12"]
        topic_edge = same_op["global:Topic:kafka:owners"]
        # Both sides of the schema equality are cited.
        assert set(topic_edge.evidence) == {"proto/owners.proto:12",
                                            "schemas/owners-value.avsc:1"}

    def test_shared_output_schema_declines_instead_of_merging(self):
        estate = operation_estate()
        result = link(estate.claims, now="2026-01-01T00:00:00+00:00",
                      aliases={}, promotions=[])
        billing = [e for e in result.edges if e.type == "SAME_OPERATION"
                   and "billing" in e.source_id]
        assert billing == []
        assert result.counters.get("r14.event_schema_ambiguous") == 1
        assert result.counters.get("r14.http_binding_unmatched") == 1
