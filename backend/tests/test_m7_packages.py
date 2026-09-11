"""M7 packages: manifests/lockfiles -> lib claims -> R3 -> VQ2 blast radius.

Precision hinges on the internal boundary: external coordinates never link
(counted instead), publish-side identity beats the namespace file, and the
version-free purl key makes version skew a one-node query.
"""

from types import SimpleNamespace

import pytest

import tracekite.services.ingest_deps as ingest_deps
from tracekite.parsers.dependency_parser import DependencyInfo
from tracekite.services.claims import is_internal_lib, lib_key
from tracekite.services.ingest_deps import (
    emit_dependency_claims, emit_publish_claims,
)
from tracekite.services.ingest_source import IngestSink
from tracekite.services.linker import r3_library
from tracekite.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput, load_confidence,
)
from tracekite.utils.hashing import generate_repo_id

INTERNAL = {"maven": {"namespaces": ["org.acme"]},
            "npm": {"scopes": ["@acme"]},
            "golang": {"module_prefixes": ["github.com/acme/"]},
            "pypi": {"prefixes": ["acme-"]}}


@pytest.fixture(autouse=True)
def _internal_boundary(monkeypatch):
    monkeypatch.setattr(ingest_deps, "_internal_namespaces_cache", INTERNAL)
    monkeypatch.setattr(r3_library, "load_internal_namespaces",
                        lambda: INTERNAL)


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


def _dep(name, version="1.0.0", dep_type="maven", **kw):
    dep = DependencyInfo(name=name, version=version, type=dep_type)
    for key, value in kw.items():
        setattr(dep, key, value)
    return dep


def _consumer(repo_id, deps, path="pom.xml"):
    sink = IngestSink()
    emit_dependency_claims(repo_id, _file(path), deps, f"file:{path}", sink)
    return _claims(sink, repo_id), sink


def _publisher(repo_id, ecosystem, name, namespace="", version="2.0.0"):
    sink = IngestSink()
    identity = SimpleNamespace(ecosystem=ecosystem, name=name,
                               namespace=namespace, version=version,
                               private=False)
    emit_publish_claims(repo_id, _file("pom.xml"), identity,
                        "file:pom", sink)
    return _claims(sink, repo_id)


def run_r3(claims, known_repos=()):
    ctx = LinkContext("linkrun_test", load_confidence(), {})
    ctx.known_repos = {c.repo_id for c in claims} | set(known_repos)
    out = ResolverOutput()
    out.extend(r3_library.resolve(ClaimIndex(claims), ctx))
    return ctx, out


class TestInternalBoundary:
    def test_purl_normalization_and_matching(self):
        assert lib_key("gradle", "billing-lib", "org.acme") \
            == "pkg:maven/org.acme/billing-lib"
        assert lib_key("pip", "Acme_Utils") == "pkg:pypi/acme-utils"
        assert is_internal_lib("pkg:maven/org.acme.billing/lib", INTERNAL)
        assert is_internal_lib("pkg:npm/@acme/ui", INTERNAL)
        assert not is_internal_lib("pkg:npm/lodash", INTERNAL)
        assert not is_internal_lib("pkg:maven/org.springframework/core", INTERNAL)

    def test_external_lockfile_rows_are_counted_not_claimed(self):
        deps = [_dep("lodash", "4.17.21", "npm", resolved=True),
                _dep("@acme/ui", "3.1.0", "npm", resolved=True)]
        claims, sink = _consumer("repo_web", deps, path="package-lock.json")
        assert [c.key for c in claims] == ["pkg:npm/@acme/ui"]
        assert sink.claims.get("lib_external_skipped") == 1

    def test_external_manifest_deps_still_claim(self):
        # Direct declarations are bounded; they stay visible even when external.
        claims, _ = _consumer("repo_api",
                              [_dep("org.springframework:spring-core", "6.1.0")])
        assert claims[0].key == "pkg:maven/org.springframework/spring-core"


class TestR3Join:
    def _estate(self):
        publisher = _publisher("repo_lib", "maven", "billing-lib", "org.acme")
        consumer_a, _ = _consumer(
            "repo_api", [_dep("org.acme:billing-lib", "2.0.0")])
        consumer_b, _ = _consumer(
            "repo_worker", [_dep("org.acme:billing-lib", "1.9.0")])
        return publisher + consumer_a + consumer_b

    def test_publisher_and_consumers_meet_at_one_rendezvous(self):
        ctx, out = run_r3(self._estate())
        libs = [r for r in out.rendezvous if r.label == "Library"]
        assert len(libs) == 1
        assert libs[0].node_id == "global:Lib:pkg:maven/org.acme/billing-lib"
        publishes = [e for e in out.edges if e.type == "PUBLISHES"]
        depends = [e for e in out.edges if e.type == "DEPENDS_ON"]
        assert {e.source_id for e in publishes} == {"repo_lib"}
        assert {e.source_id for e in depends} == {"repo_api", "repo_worker"}

    def test_consumer_edges_name_the_publishing_repo(self):
        _, out = run_r3(self._estate())
        depends = [e for e in out.edges if e.type == "DEPENDS_ON"]
        assert all(e.target_repo_id == "repo_lib" for e in depends)
        assert all(e.cross_repo for e in depends)

    def test_version_skew_is_surfaced(self):
        ctx, out = run_r3(self._estate())
        assert ctx.counters["r3.version_skew"] == 1
        versions = {e.extra_props.get("version")
                    for e in out.edges if e.type == "DEPENDS_ON"}
        assert versions == {"2.0.0", "1.9.0"}

    def test_repo_level_dependency_edge(self):
        _, out = run_r3(self._estate())
        repo_edges = [e for e in out.edges if e.type == "DEPENDS_ON_REPO"]
        assert {(e.source_id, e.target_id) for e in repo_edges} \
            == {("repo_api", "repo_lib"), ("repo_worker", "repo_lib")}

    def test_internal_namespace_links_without_publisher(self):
        claims, _ = _consumer("repo_api", [_dep("org.acme:events", "1.0.0")])
        ctx, out = run_r3(claims)
        depends = [e for e in out.edges if e.type == "DEPENDS_ON"]
        assert depends and depends[0].match_type == "internal_namespace"
        assert depends[0].target_repo_id == ""

    def test_external_consumed_key_never_links(self):
        claims, _ = _consumer("repo_api", [_dep("com.google.guava:guava")])
        ctx, out = run_r3(claims)
        assert not [e for e in out.edges if e.type == "DEPENDS_ON"]
        assert ctx.counters["r3.external_skipped"] == 1


class TestGoModuleBinding:
    def test_module_path_binds_to_ingested_repo(self):
        lib_repo = generate_repo_id("acme", "lib", "github.com")
        deps = [_dep("github.com/acme/lib", "v1.2.3", "go", resolved=False)]
        claims, _ = _consumer("repo_api", deps, path="go.mod")
        ctx, out = run_r3(claims, known_repos={lib_repo})
        depends = [e for e in out.edges if e.type == "DEPENDS_ON"]
        assert depends[0].match_type == "go_module_path"
        assert depends[0].target_repo_id == lib_repo
        assert ctx.counters["r3.go_module_bound"] == 1

    def test_unknown_module_stays_namespace_matched_only(self):
        deps = [_dep("github.com/acme/ghost", "v0.1.0", "go")]
        claims, _ = _consumer("repo_api", deps, path="go.mod")
        ctx, out = run_r3(claims)
        depends = [e for e in out.edges if e.type == "DEPENDS_ON"]
        assert depends[0].match_type == "internal_namespace"
        assert depends[0].target_repo_id == ""


class TestPublishConfidence:
    def test_tiers_ordered_publish_over_lock_over_manifest(self):
        publisher = _publisher("repo_lib", "npm", "ui", "@acme")
        locked, _ = _consumer("repo_a", [_dep("@acme/ui", "3.0.0", "npm",
                                              resolved=True)],
                              path="package-lock.json")
        declared, _ = _consumer("repo_b", [_dep("@acme/ui", "^3.0.0", "npm")],
                                path="package.json")
        _, out = run_r3(publisher + locked + declared)
        by_repo = {e.source_id: e.confidence for e in out.edges
                   if e.type == "DEPENDS_ON"}
        publish = [e for e in out.edges if e.type == "PUBLISHES"][0]
        assert publish.confidence > by_repo["repo_a"] > by_repo["repo_b"]
