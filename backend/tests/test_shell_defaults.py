"""`${VAR:-default}` declares a value; a composite declares nothing.

Compose files define most real service hosts this way. Before this, the
raw string tripped `is_unrendered_template` and the whole definition was
declined — 442 env reads in the reference estate had no resolvable
definition while the compose file next to them said what the default was.

The precision hazard is that a host-shaped default need not be a host:
`DB_USER=${DB_USER:-postgres}` would join to a service called postgres.
Only keys whose NAME says they carry a network target contribute one.
"""

from adduce.services.env_extractor import shell_default


class TestShellDefault:
    def test_reads_the_fallback(self):
        assert shell_default("${DB_HOST:-platform-db}") == "platform-db"
        assert shell_default("${PORT:-8080}") == "8080"

    def test_whitespace_is_tolerated(self):
        assert shell_default("  ${DB_HOST:-platform-db}  ") == "platform-db"

    def test_a_composite_declares_nothing(self):
        """Assembling `http://{host}:{port}` from two defaults is rendering
        by hand — the same line the Helm chase refuses to cross."""
        assert shell_default("http://${HOST:-db}:${PORT:-5432}/x") is None

    def test_a_plain_reference_has_no_default(self):
        assert shell_default("${DB_HOST}") is None

    def test_an_empty_default_is_not_a_value(self):
        assert shell_default("${DB_HOST:-}") is None

    def test_a_nested_template_is_not_a_value(self):
        assert shell_default("${DB_HOST:-${OTHER}}") is None

    def test_a_literal_is_not_a_default(self):
        assert shell_default("platform-db") is None
        assert shell_default("") is None


class TestOnlyEndpointKeysContributeAHost:
    """The claim-level gate, exercised through the real compose emitter."""

    def emit(self, env_line):
        from adduce.parsers.docker_parser import parse_docker_compose
        from adduce.services.ingest_claims import emit_compose_claims
        from adduce.services.ingest_source import IngestSink
        from types import SimpleNamespace
        compose = f"""
name: shopstack
services:
  web:
    image: acme/web:1
    environment:
      - {env_line}
  inventory-svc:
    image: acme/inv:1
  postgres:
    image: postgres:16
"""
        sink = IngestSink()
        resources = parse_docker_compose("docker-compose.yml", compose)
        emit_compose_claims(
            "repo_shop", SimpleNamespace(path="docker-compose.yml",
                                         language="yaml"),
            resources, {r.name: f"d:{r.name}" for r in resources}, sink)
        return [n for n in sink.nodes
                if n.type == "ContractClaim"
                and (n.metadata or {}).get("via") == "env_host_default"]

    def test_an_endpoint_key_contributes_its_default_host(self):
        [claim] = self.emit("INVENTORY_HOST=${INVENTORY_HOST:-inventory-svc}")
        assert claim.extra_props["service_hint"] == "inventory-svc"
        assert claim.metadata["defaulted"] is True

    def test_a_username_that_looks_like_a_host_contributes_nothing(self):
        assert self.emit("DB_USER=${DB_USER:-postgres}") == []

    def test_a_numeric_default_never_becomes_a_hostname(self):
        assert self.emit("SERVER_PORT=${SERVER_PORT:-5432}") == []

    def test_a_url_default_still_resolves_through_redaction(self):
        [claim] = self.emit("INVENTORY_URL=${INVENTORY_URL:-http://inventory-svc:8080}")
        assert claim.extra_props["service_hint"] == "inventory-svc"


class TestEnvEvidenceCitesTheDeclaringLine:
    """The receipt names the line that asserts the fact, not the resource
    header. Found from the UI: a true edge cited `name: visits-service` on
    line 7 while the wavefront value it was derived from sat on line 58."""

    MANIFEST = """apiVersion: apps/v1
kind: Deployment
metadata:
  labels:
    app: visits-service
  name: visits-service
spec:
  template:
    spec:
      containers:
        - name: app
          image: acme/visits:1
          env:
            - name: SOME_FLAG
              value: "on"
            - name: METRICS_WAVEFRONT_URI
              value: proxy://wavefront-proxy.demo.svc.cluster.local:2878
"""

    def claims(self):
        from adduce.parsers.kubernetes_parser import parse_kubernetes_yaml
        from adduce.services.ingest_claims import emit_k8s_claims
        from adduce.services.ingest_source import IngestSink
        from types import SimpleNamespace
        sink = IngestSink()
        resources = parse_kubernetes_yaml("k8s/visits.yaml", self.MANIFEST)
        emit_k8s_claims("repo_v", SimpleNamespace(path="k8s/visits.yaml"),
                        resources,
                        {f"{r.kind}/{r.name}": f"n:{r.name}" for r in resources},
                        sink)
        return [n for n in sink.nodes if n.type == "ContractClaim"]

    def test_the_env_claim_cites_its_own_declaration_line(self):
        lines = self.MANIFEST.split("\n")
        [claim] = [c for c in self.claims()
                   if (c.metadata or {}).get("env_name")
                   == "METRICS_WAVEFRONT_URI"]
        cited = int(claim.extra_props["evidence"][0].rsplit(":", 1)[1])
        assert "METRICS_WAVEFRONT_URI" in lines[cited - 1], (
            f"cited line {cited} says {lines[cited - 1]!r}")

    def test_two_vars_cite_two_different_lines(self):
        cited = {(c.metadata or {}).get("env_name"):
                 int(c.extra_props["evidence"][0].rsplit(":", 1)[1])
                 for c in self.claims() if (c.metadata or {}).get("env_name")}
        assert cited["SOME_FLAG"] != cited["METRICS_WAVEFRONT_URI"]


class TestComposeEvidenceCitesTheEntryLine:
    """Same rule as the k8s env fix, for compose: the receipt names the
    `- dep` or `KEY=value` line, not the service header. Found by auditing
    every service-map edge against the clones: schema-registry -> zookeeper
    cited `schema-registry:` four lines above the `- zookeeper` it rests on.
    """

    COMPOSE = """name: shop
services:
  storefront:
    image: acme/storefront:1
    depends_on:
      - orders-api
      - payments
    environment:
      - INVENTORY_URL=http://inventory-svc:8080
  orders-api:
    image: acme/orders:1
  payments:
    image: acme/pay:1
  inventory-svc:
    image: acme/inv:1
"""

    def claims(self):
        from adduce.parsers.docker_parser import parse_docker_compose
        from adduce.services.ingest_claims import emit_compose_claims
        from adduce.services.ingest_source import IngestSink
        from types import SimpleNamespace
        sink = IngestSink()
        resources = parse_docker_compose("docker-compose.yml", self.COMPOSE)
        emit_compose_claims("r", SimpleNamespace(path="docker-compose.yml",
                                                 language="yaml"),
                            resources, {r.name: f"d:{r.name}" for r in resources},
                            sink)
        return [n for n in sink.nodes if n.type == "ContractClaim"]

    def cited_line(self, key, via, env_key=None):
        # `subject` participates in the claim id but is not stored as a
        # node property; the discriminator that IS stored is metadata.
        matches = [c for c in self.claims()
                   if c.extra_props.get("key") == key
                   and (c.metadata or {}).get("via") == via
                   and (env_key is None
                        or (c.metadata or {}).get("env_key") == env_key)]
        [claim] = matches
        return int(claim.extra_props["evidence"][0].rsplit(":", 1)[1])

    def test_each_dep_cites_its_own_entry(self):
        lines = self.COMPOSE.split("\n")
        orders = self.cited_line("shop:orders-api", "depends_on")
        payments = self.cited_line("shop:payments", "depends_on")
        assert lines[orders - 1].strip() == "- orders-api"
        assert lines[payments - 1].strip() == "- payments"
        assert orders != payments

    def test_an_env_host_cites_the_pair_not_the_header(self):
        lines = self.COMPOSE.split("\n")
        cited = self.cited_line("shop:inventory-svc", "env_host",
                                env_key="INVENTORY_URL")
        assert "INVENTORY_URL=" in lines[cited - 1]

    def test_the_service_itself_still_cites_its_header(self):
        # The header IS the declaration of the service; only entry-derived
        # claims move off it.
        lines = self.COMPOSE.split("\n")
        [claim] = [c for c in self.claims()
                   if c.extra_props.get("direction") == "provides"
                   and c.extra_props.get("key") == "shop:storefront"
                   and c.extra_props.get("kind") == "svcname"]
        cited = int(claim.extra_props["evidence"][0].rsplit(":", 1)[1])
        assert lines[cited - 1].strip() == "storefront:"


class TestBuiltFromCitesTheContextLine:
    COMPOSE = """name: shop
services:
  orders-api:
    build:
      context: ./orders
    ports:
      - "8080:8080"
"""

    def test_the_provides_claim_carries_the_build_line(self):
        from adduce.parsers.docker_parser import parse_docker_compose
        lines = self.COMPOSE.split("\n")
        [svc] = [r for r in parse_docker_compose("docker-compose.yml",
                                                 self.COMPOSE)
                 if r.type == "service"]
        cited = svc.entry_lines["build"]
        assert lines[cited - 1].strip() == "context: ./orders"

    def test_the_built_from_edge_cites_it(self):
        from tests.test_alias_suggestions import claim
        from adduce.services.linker.engine import link
        estate = [claim("svcname", "provides", "shop:orders-api",
                        repo="repo_o",
                        attrs={"source": "compose", "build_context": "./orders",
                               "build_line": 5},
                        evidence=["docker-compose.yml:3"])]
        result = link(estate, now="2026-01-01T00:00:00+00:00", aliases={},
                      promotions=[])
        [bf] = [e for e in result.edges if e.type == "BUILT_FROM"]
        assert bf.evidence == ["docker-compose.yml:5"]


class TestFusedGatewayEdgeKeepsTheRouteReceipt:
    def test_route_line_survives_the_rollup(self):
        """A gateway-relative call site never names its target; the route
        table line does, and R7 appends it last. The rollup used to keep
        only evidence[:1], so the fused edge cited a receipt the reader
        could not confirm."""
        from tests.test_path_algebra import two_hop_estate
        from adduce.services.linker.engine import link
        result = link(two_hop_estate(), now="2026-01-01T00:00:00+00:00",
                      aliases={}, promotions=[])
        [cs] = [e for e in result.edges if e.type == "CALLS_SERVICE"
                and "gateway_rewrite" in (e.extra_props.get("via") or [])]
        assert "repo_web/src/api.ts:41" in cs.evidence      # the call
        assert any("nginx.conf" in ev or "mesh.yml" in ev
                   for ev in cs.evidence), cs.evidence      # the naming


class TestLocatorTallyDoesNotShortCircuit:
    """Regression: a bare `build:` header stored a scratch key inside the
    tally dict, so the early-exit fired one entry short — and the entry it
    skipped on the first real estate was the depends_on that came after the
    build block. Found by auditing the UI's edges against the clones."""

    COMPOSE = """name: shop
services:
  web:
    build:
      context: .
      dockerfile: apps/web/Dockerfile
    environment:
      - PORT=3000
    depends_on:
      cache:
        condition: service_healthy
  cache:
    image: acme/cache:1
"""

    def test_the_dep_after_a_build_block_is_still_located(self):
        from adduce.parsers.docker_parser import parse_docker_compose
        lines = self.COMPOSE.split("\n")
        [web] = [r for r in parse_docker_compose("docker-compose.yml",
                                                 self.COMPOSE)
                 if r.type == "service" and r.name == "web"]
        dep = web.entry_lines["dep:cache"]
        assert lines[dep - 1].strip() == "cache:"
        assert lines[web.entry_lines["build"] - 1].strip() == "context: ."
        assert lines[web.entry_lines["env:PORT"] - 1].strip() == "- PORT=3000"


class TestAnchorMergedEnvCitesTheAnchor:
    """`<<: *shared-env` puts the pair in the service without ever writing
    the key in its block. The pair is asserted once — at the anchor — and
    that line is the receipt; the header fallback pointed a reader at a
    block that visibly does not contain the variable."""

    COMPOSE = """name: shop
x-db-env: &db-env
  DB_HOST: ${DB_HOST:-platform-db}
services:
  registry:
    image: acme/registry:1
    environment:
      <<: *db-env
      LISTEN_ADDR: ":8080"
  platform-db:
    image: postgres:16
"""

    def test_the_merged_pair_cites_the_anchor_line(self):
        from adduce.parsers.docker_parser import parse_docker_compose
        lines = self.COMPOSE.split("\n")
        [svc] = [r for r in parse_docker_compose("docker-compose.yml",
                                                 self.COMPOSE)
                 if r.type == "service" and r.name == "registry"]
        assert "DB_HOST" in svc.env_pairs          # the merge expanded
        cited = svc.entry_lines["env:DB_HOST"]
        assert lines[cited - 1].strip().startswith("DB_HOST:")

    def test_inline_pairs_still_cite_their_own_block(self):
        from adduce.parsers.docker_parser import parse_docker_compose
        lines = self.COMPOSE.split("\n")
        [svc] = [r for r in parse_docker_compose("docker-compose.yml",
                                                 self.COMPOSE)
                 if r.type == "service" and r.name == "registry"]
        cited = svc.entry_lines["env:LISTEN_ADDR"]
        assert lines[cited - 1].strip().startswith("LISTEN_ADDR:")


class TestFixtureEndpointsAreNotApiSurface:
    """`jc.delete("/path")` against a mocked client in a test file became a
    DELETE provider endpoint. The generic discriminator is provenance, not a
    receiver-name blocklist — no list can enumerate every variable name."""

    def _records(self, path):
        from adduce.services.ingest_source import _process_endpoints, IngestSink
        from types import SimpleNamespace
        src = SimpleNamespace(api_endpoints=[SimpleNamespace(
            method="DELETE", path="/path", framework="fastapi",
            handler_name="", controller_name="", line=153)])
        sink = IngestSink()
        recs = _process_endpoints(
            "r", SimpleNamespace(path=path, language="python"), src,
            "f:1", sink, [], {"endpoints": 0})
        return recs, sink

    def test_a_test_files_endpoint_is_skipped_and_counted(self):
        recs, sink = self._records("shared/tests/test_client.py")
        assert recs == []
        assert not [n for n in sink.nodes if n.type == "ApiEndpoint"]

    def test_a_production_files_endpoint_still_mints(self):
        recs, sink = self._records("shared/src/server.py")
        assert len(recs) == 1
