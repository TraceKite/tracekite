"""M10 ownership & observability: parsers -> owner/svcname claims -> R12.

Ownership statements come from three places that disagree in predictable ways
(catalog names a service's owner, CODEOWNERS names a path's owner, DD tags
name a deployment's team); all meet at Team rendezvous. Observability names
feed R0 as corroborating aliases at their own hint tier — they never mint
topology.
"""

from types import SimpleNamespace

from tracekite.parsers.ownership_parser import (
    extract_observability_identity, parse_catalog_info, parse_codeowners,
)
from tracekite.services.claims import PROVIDES, ContractClaim
from tracekite.services.ingest_claims import (
    add_claim, emit_catalog_claims, emit_codeowners_claims,
    emit_observability_claims,
)
from tracekite.services.ingest_source import IngestSink
from tracekite.services.linker import r0_alias, r12_owner
from tracekite.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput, load_confidence,
)

CATALOG = """
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: orders-service
  annotations:
    pagerduty.com/service-id: PD12345
spec:
  type: service
  lifecycle: production
  owner: group:default/payments-team
  system: checkout
"""

CODEOWNERS = """
# fallback
*            @acme/platform-team
/backend/    @acme/payments-team @jane
*.tf         ops@acme.io
"""

DATADOG_ENV = """
DD_SERVICE=orders-service
DD_ENV=prod
DD_TAGS=team:payments-team,region:us-east-1
"""


def _file(path):
    return SimpleNamespace(path=path, language=None)


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


def _service_claim(repo_id, name):
    sink = IngestSink()
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="svcname", direction=PROVIDES,
        key=f"prod:{name}", service_hint=name, hint_source="config",
        evidence=["deploy/app.yaml:1"], subject=f"svc/{name}",
        attrs={"source": "k8s", "workload": name},
    ), "file:deploy", sink)
    return _claims(sink, repo_id)


def run_linker(claims):
    ctx = LinkContext("linkrun_test", load_confidence(), {})
    ctx.known_repos = {c.repo_id for c in claims}
    index = ClaimIndex(claims)
    out = ResolverOutput()
    for module in (r0_alias, r12_owner):
        out.extend(module.resolve(index, ctx))
    return ctx, out


class TestCatalogOwnership:
    def _estate(self):
        sink = IngestSink()
        entities = parse_catalog_info("catalog-info.yaml", CATALOG)
        emit_catalog_claims("repo_orders", _file("catalog-info.yaml"),
                            entities, "file:catalog", sink)
        return _claims(sink, "repo_orders")

    def test_component_owner_becomes_team_rendezvous(self):
        ctx, out = run_linker(self._estate())
        teams = [r for r in out.rendezvous if r.label == "Team"]
        assert [t.props["name"] for t in teams] == ["payments-team"]
        assert ctx.counters["r12.teams"] == 1

    def test_repo_owned_by_team(self):
        _, out = run_linker(self._estate())
        owned = [e for e in out.edges if e.type == "OWNED_BY"
                 and e.source_id == "repo_orders"]
        assert owned and owned[0].target_id == "global:Team:team:payments-team"
        assert owned[0].match_type == "catalog"

    def test_service_owned_when_entity_resolves(self):
        claims = self._estate() + _service_claim("repo_orders",
                                                 "orders-service")
        ctx, out = run_linker(claims)
        service_owned = [e for e in out.edges if e.type == "OWNED_BY"
                         and e.source_label == "Service"]
        assert service_owned
        assert service_owned[0].extra_props["pagerduty_service"] == "PD12345"
        assert ctx.counters["r12.service_owned"] == 1

    def test_unresolvable_entity_is_counted_not_guessed(self):
        # A System's owner claim carries an entity no svcname claim aliases
        # (only Component/API alias service names), so nothing mints a
        # Service for it — counted, not attributed.
        system_only = """
apiVersion: backstage.io/v1alpha1
kind: System
metadata:
  name: checkout
spec:
  owner: group:default/checkout-leads
"""
        sink = IngestSink()
        entities = parse_catalog_info("catalog-info.yaml", system_only)
        emit_catalog_claims("repo_sys", _file("catalog-info.yaml"),
                            entities, "file:catalog", sink)
        ctx, out = run_linker(_claims(sink, "repo_sys"))
        assert ctx.counters["r12.entity_unresolved"] == 1
        assert not [e for e in out.edges if e.source_label == "Service"]

    def test_catalog_also_aliases_the_service_name(self):
        svcnames = [c for c in self._estate() if c.kind == "svcname"]
        assert svcnames and svcnames[0].hint_source == "catalog"


class TestCodeowners:
    def test_team_rules_claim_individuals_stay_attrs(self):
        sink = IngestSink()
        rules = parse_codeowners("CODEOWNERS", CODEOWNERS)
        emit_codeowners_claims("repo_infra", _file("CODEOWNERS"), rules,
                               "file:codeowners", sink)
        claims = _claims(sink, "repo_infra")
        teams = {c.attrs["team"] for c in claims}
        assert teams == {"acme/platform-team", "acme/payments-team"}
        backend = [c for c in claims
                   if c.attrs["team"] == "acme/payments-team"][0]
        assert backend.attrs["individuals"] == ["jane"]
        # The email-only rule produced no claim at all.
        assert not any("ops@acme.io" in str(c.attrs) for c in claims)

    def test_pattern_survives_to_the_edge(self):
        sink = IngestSink()
        rules = parse_codeowners("CODEOWNERS", CODEOWNERS)
        emit_codeowners_claims("repo_infra", _file("CODEOWNERS"), rules,
                               "file:codeowners", sink)
        _, out = run_linker(_claims(sink, "repo_infra"))
        owned = [e for e in out.edges if e.type == "OWNED_BY"]
        patterns = {e.extra_props.get("pattern") for e in owned}
        assert "/backend/" in patterns


class TestObservability:
    def test_dd_service_is_an_alias_signal_with_team(self):
        sink = IngestSink()
        identities = extract_observability_identity(".env.prod", DATADOG_ENV)
        emit_observability_claims("repo_orders", _file(".env.prod"),
                                  identities, "file:env", sink)
        claims = _claims(sink, "repo_orders")
        svcnames = [c for c in claims if c.kind == "svcname"]
        assert svcnames[0].service_hint == "orders-service"
        assert svcnames[0].hint_source == "observability"
        owners = [c for c in claims if c.kind == "owner"]
        assert owners and owners[0].attrs["team"] == "payments-team"

    def test_observability_owner_tier_is_lowest(self):
        sink = IngestSink()
        identities = extract_observability_identity(".env.prod", DATADOG_ENV)
        emit_observability_claims("repo_orders", _file(".env.prod"),
                                  identities, "file:env", sink)
        _, out = run_linker(_claims(sink, "repo_orders"))
        owned = [e for e in out.edges if e.type == "OWNED_BY"]
        assert owned and owned[0].match_type == "observability"
        assert owned[0].confidence == 0.8
