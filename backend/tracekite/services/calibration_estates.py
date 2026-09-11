"""Labelled estates for the R10 and R11 tiers.

These seven tiers served edges with no measured row for as long as the
resolvers have existed — invisible to the coverage gate because its section
list predated them. The estates are authored as raw `ClaimRecord`s rather
than through extractors: what is being measured is the *join and its
pricing*, and the extractor-to-claim path has its own tests.

Each estate labels its declines too. A forbidden edge here is constructed
truth — an FP is a resolver bug, not a fixture problem.
"""

from tracekite.services.calibration import LabeledEstate
from tracekite.services.linker.base import ClaimRecord


def _claim(cid: str, repo: str, kind: str, direction: str, key: str,
           attrs: dict, evidence: str) -> ClaimRecord:
    return ClaimRecord(
        id=cid, repo_id=repo, kind=kind, direction=direction, key=key,
        service_hint=None, hint_source="none", matchable=True,
        evidence=[evidence], attrs=attrs,
        evidence_node_id=f"node:{cid}", evidence_node_type="File")


def dataset_estate() -> LabeledEstate:
    """R10: declared, inferred and literal joins, plus the bare-table decline."""
    claims = [
        # A migration declares table:owners; a reader in another repo joins
        # through the single-declarer rule.
        _claim("d1", "repo_owners", "dataset", "provides", "table:owners",
               {"declares": True, "system": "sql"},
               "db/migration/V2__create_owners.sql:1"),
        _claim("d2", "repo_reports", "dataset", "consumes", "table:owners",
               {"system": "sql"}, "src/load.py:12"),
        # Lineage inference: a notebook writes a warehouse table the tool
        # inferred from context rather than read literally.
        _claim("d3", "repo_analytics", "dataset", "consumes",
               "wh:analytics.events", {"inferred": True, "system": "wh"},
               "notebooks/daily.py:33"),
        # A distinctive namespace joins freely on equal spelling.
        _claim("d4", "repo_ingestor", "dataset", "provides", "index:visits",
               {"system": "es"}, "src/writer.py:8"),
        # The trap: a bare table name in two repos with no declarer. Half
        # the estate has a `users` table; joining them is the invented edge.
        _claim("d5", "repo_a", "dataset", "consumes", "table:users",
               {"system": "sql"}, "src/a.py:5"),
        _claim("d6", "repo_b", "dataset", "consumes", "table:users",
               {"system": "sql"}, "src/b.py:5"),
    ]
    return LabeledEstate(
        name="datasets_r10", claims=claims,
        expect=[
            {"tier": "r10.declared", "type": "WRITES_TO",
             "match_type": "dataset_declared", "claim_key": "table:owners",
             "source_repo_id": "repo_owners"},
            {"tier": "r10.literal", "type": "READS_FROM",
             "match_type": "dataset_literal", "claim_key": "table:owners",
             "source_repo_id": "repo_reports"},
            {"tier": "r10.inferred", "type": "READS_FROM",
             "match_type": "dataset_inferred",
             "claim_key": "wh:analytics.events"},
            {"tier": "r10.literal", "type": "WRITES_TO",
             "match_type": "dataset_literal", "claim_key": "index:visits"},
        ],
        forbid=[
            # No declarer, two repos: the cross-repo join must decline.
            {"tier": "r10.literal", "claim_key": "table:users"},
        ])


def agent_estate() -> LabeledEstate:
    """R11: MCP registration/config and A2A card/url, plus the ambiguous
    server decline."""
    claims = [
        # FastMCP("github") registers a tool; a client config names the
        # server and binds to every tool it registers.
        _claim("a1", "repo_mcp_github", "mcpop", "provides",
               "mcp:github/create_issue",
               {"server": "github", "tool": "create_issue"},
               "src/server.py:14"),
        _claim("a2", "repo_assistant", "mcpop", "consumes", "mcp:github/*",
               {"server": "github"}, ".mcp.json:3"),
        # An A2A card exposes a skill at a URL; a call site names the URL.
        _claim("a3", "repo_travel", "a2aop", "provides",
               "a2a:travel-agent/plan_trip",
               {"agent": "travel-agent", "skill": "plan_trip",
                "url": "https://agents.internal/travel"},
               "agent-card.json:1"),
        _claim("a4", "repo_portal", "a2aop", "consumes",
               "a2a:url:https://agents.internal/travel", {},
               "src/portal/client.py:21"),
        # Two repos both registering FastMCP("shared"): picking an owner
        # would be a coin flip, so the join declines.
        _claim("a5", "repo_x", "mcpop", "provides", "mcp:shared/tool_x",
               {"server": "shared", "tool": "tool_x"}, "src/x.py:1"),
        _claim("a6", "repo_y", "mcpop", "provides", "mcp:shared/tool_x",
               {"server": "shared", "tool": "tool_x"}, "src/y.py:1"),
    ]
    return LabeledEstate(
        name="agents_r11", claims=claims,
        expect=[
            {"tier": "r11.registration", "type": "EXPOSES",
             "match_type": "mcp_registration",
             "claim_key": "mcp:github/create_issue"},
            {"tier": "r11.config", "type": "INVOKES",
             "match_type": "mcp_config",
             "source_repo_id": "repo_assistant"},
            {"tier": "r11.card", "type": "EXPOSES",
             "match_type": "a2a_card",
             "claim_key": "a2a:travel-agent/plan_trip"},
            {"tier": "r11.url_resolved", "type": "INVOKES",
             "match_type": "a2a_url", "source_repo_id": "repo_portal",
             "target_repo_id": "repo_travel"},
        ],
        forbid=[
            {"tier": "r11.registration", "claim_key": "mcp:shared/tool_x"},
        ])


def webhook_estate() -> LabeledEstate:
    """R13: a registered callback joins the receiver's own route — and a
    callback whose receiver declares no such route is declined."""
    claims = [
        # The registrar's own service, so the edge has a source.
        _claim("w1", "repo_ours", "svcname", "provides", "prod:ours",
               {"source": "k8s", "workload": "ours"}, "deploy/ours.yaml:1"),
        # The receiver's identity and its route.
        _claim("w2", "repo_ours", "http", "provides", "POST:/hooks/stripe",
               {"source": "annotation"}, "src/hooks.py:8"),
        # The registration, callback pointing at the route above.
        _claim("w3", "repo_ours", "webhook", "consumes",
               "webhook:POST:/hooks/stripe",
               {"source": "webhook_registration", "deliverer": "stripe"},
               "src/billing/setup.py:14"),
        # Decline: a callback to a path nobody declares.
        _claim("w4", "repo_ours", "webhook", "consumes",
               "webhook:POST:/hooks/ghost",
               {"source": "webhook_registration"}, "src/ghost.py:3"),
    ]
    for c in claims:
        if c.kind in ("http", "webhook"):
            c.service_hint = "ours"
            c.hint_source = "host"
    return LabeledEstate(
        name="webhooks_r13", claims=claims,
        expect=[
            {"tier": "r13.registered", "type": "REGISTERS_WEBHOOK",
             "match_type": "webhook_registration",
             "claim_key": "webhook:POST:/hooks/stripe"},
        ],
        forbid=[
            {"tier": "r13.registered",
             "claim_key": "webhook:POST:/hooks/ghost"},
        ])


def policy_estate() -> LabeledEstate:
    """R2 policy: a mesh rule joins by selector and service account — and a
    policy whose target selector matches no workload names no edge."""
    claims = [
        _claim("p1", "repo_mesh", "svcname", "provides", "prod:billing",
               {"source": "k8s", "workload": "billing",
                "namespace": "prod", "pod_labels": ["app=billing"]},
               "deploy/billing.yaml:1"),
        _claim("p2", "repo_mesh", "svcname", "provides", "prod:orders",
               {"source": "k8s", "workload": "orders",
                "namespace": "prod", "pod_labels": ["app=orders"]},
               "deploy/orders.yaml:1"),
        _claim("p3", "repo_mesh", "policy", "provides", "prod:app=billing",
               {"source": "authorization_policy", "action": "ALLOW",
                "target_selector": ["app=billing"],
                "source_kind": "service_account", "source_ref": "orders",
                "namespace": "prod"},
               "mesh/allow-orders.yaml:6"),
        # Decline: a policy about a selector nobody wears.
        _claim("p4", "repo_mesh", "policy", "provides", "prod:app=ghost",
               {"source": "network_policy", "action": "ALLOW",
                "target_selector": ["app=ghost"],
                "source_kind": "labels", "source_ref": ["app=orders"],
                "namespace": "prod"},
               "mesh/ghost.yaml:3"),
    ]
    return LabeledEstate(
        name="policy_r2", claims=claims,
        expect=[
            {"tier": "r2.policy", "type": "PERMITS_TRAFFIC",
             "via": "mesh_policy_allow"},
        ],
        forbid=[
            {"tier": "r2.policy", "claim_key": "prod:app=ghost"},
        ])


def operation_estate() -> LabeledEstate:
    """R14: cross-protocol ties by authored equivalence, plus both declines.

    The http tie needs a real HttpContract on the other side, so the
    estate carries the provider claim R7 mints it from; the topic tie
    needs the Topic rendezvous R6 mints from the avro claim.
    """
    claims = [
        # An rpc whose proto declares its own HTTP binding.
        _claim("o1", "repo_owners", "grpcop", "provides",
               "demo.owners.OwnerService/GetOwner",
               {"source": "proto", "package": "demo.owners",
                "service": "demo.owners.OwnerService", "rpc": "GetOwner",
                "input_type": "GetOwnerRequest", "output_type": "OwnerEvent",
                "streaming": "unary", "http_method": "GET",
                "http_template": "/v1/owners/{id}"},
               "proto/owners.proto:12"),
        _claim("o2", "repo_owners", "http", "provides",
               "GET:/v1/owners/{id}", {"framework": "grpc-gateway"},
               "gateway/owners.go:40"),
        # The avro subject whose record IS the rpc's qualified output.
        _claim("o3", "repo_owners", "topic", "provides", "kafka:owners",
               {"source": "avro", "system": "kafka", "declares": True,
                "schema": "demo.owners.OwnerEvent",
                "subject": "owners-value"},
               "schemas/owners-value.avsc:1"),
        # Decline 1: a binding whose contract nobody provides.
        _claim("o4", "repo_pets", "grpcop", "provides",
               "demo.pets.PetService/GetPet",
               {"source": "proto", "package": "demo.pets",
                "service": "demo.pets.PetService", "rpc": "GetPet",
                "input_type": "GetPetRequest", "output_type": "Pet",
                "streaming": "unary", "http_method": "GET",
                "http_template": "/v1/pets/{id}"},
               "proto/pets.proto:9"),
        # Decline 2: one schema named as the output of TWO rpcs — a wrong
        # SAME_OPERATION merges two operations' blast radii.
        _claim("o5", "repo_billing", "grpcop", "provides",
               "demo.billing.BillingService/Charge",
               {"source": "proto", "package": "demo.billing",
                "service": "demo.billing.BillingService", "rpc": "Charge",
                "input_type": "ChargeRequest", "output_type": "Receipt",
                "streaming": "unary", "http_method": "",
                "http_template": ""},
               "proto/billing.proto:7"),
        _claim("o6", "repo_billing", "grpcop", "provides",
               "demo.billing.BillingService/Refund",
               {"source": "proto", "package": "demo.billing",
                "service": "demo.billing.BillingService", "rpc": "Refund",
                "input_type": "RefundRequest", "output_type": "Receipt",
                "streaming": "unary", "http_method": "",
                "http_template": ""},
               "proto/billing.proto:11"),
        _claim("o7", "repo_billing", "topic", "provides", "kafka:receipts",
               {"source": "avro", "system": "kafka", "declares": True,
                "schema": "demo.billing.Receipt",
                "subject": "receipts-value"},
               "schemas/receipts-value.avsc:1"),
    ]
    return LabeledEstate(
        name="operations_r14", claims=claims,
        expect=[
            {"tier": "r14.http_binding", "type": "SAME_OPERATION",
             "match_type": "http_binding",
             "claim_key": "demo.owners.OwnerService/GetOwner"},
            {"tier": "r14.event_schema", "type": "SAME_OPERATION",
             "match_type": "event_schema",
             "claim_key": "demo.owners.OwnerService/GetOwner"},
        ],
        forbid=[
            {"tier": "r14.http_binding", "type": "SAME_OPERATION",
             "claim_key": "demo.pets.PetService/GetPet"},
            {"tier": "r14.event_schema", "type": "SAME_OPERATION",
             "claim_key": "demo.billing.BillingService/Charge"},
            {"tier": "r14.event_schema", "type": "SAME_OPERATION",
             "claim_key": "demo.billing.BillingService/Refund"},
        ])
