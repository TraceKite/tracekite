"""Pipeline tests: symbol identity, endpoint dedupe, redacted config, fixtures."""

import dataclasses
import json
import os
from types import SimpleNamespace

from evigraph.config import settings
from evigraph.parsers.base import ParsedApiEndpoint, ParsedEntity, ParseResult
from evigraph.parsers.config_parser import ConfigEntry, ConfigParseResult
from evigraph.parsers.dependency_parser import DependencyInfo
from evigraph.services.file_scanner import scan_repository
from evigraph.services.ingest_artifacts import process_config, process_dependencies
from evigraph.services.ingest_source import IngestSink, process_source_file
from evigraph import engine_config
from evigraph.services.scan import build_graph

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _file(path="src/App.java", language="Java", size=1000):
    return SimpleNamespace(path=path, name=os.path.basename(path),
                           language=language, size_bytes=size, is_test=False,
                           absolute_path="/nonexistent")


def _entity(name, type_="method", start=1, end=5, parent=None, params=None):
    return ParsedEntity(name=name, type=type_, start_line=start, end_line=end,
                        signature=f"{name}()", modifiers=[], annotations=[],
                        metadata={"parent_class": parent,
                                  "parameters": params or []})


def _source(entities=(), endpoints=(), imports=(), calls=()):
    result = ParseResult()
    result.entities.extend(entities)
    result.api_endpoints.extend(endpoints)
    result.imports.extend(imports)
    result.method_calls.extend(calls)
    return result


class TestSymbolIdentity:
    def test_same_name_same_arity_get_occurrence_indexes(self):
        sink = IngestSink()
        source = _source(entities=[
            _entity("handle", start=1), _entity("handle", start=20),
        ])
        process_source_file("r1", _file(), source, "file-node", sink, "full")
        methods = [n for n in sink.nodes if n.type == "Method"]
        assert len(methods) == 2
        assert methods[0].id != methods[1].id

    def test_ids_survive_edits_above_symbol(self):
        """Adding an unrelated symbol earlier in the file must not churn ids."""
        first = IngestSink()
        process_source_file("r1", _file(), _source(entities=[
            _entity("alpha", start=10), _entity("beta", start=30),
        ]), "file-node", first, "full")

        second = IngestSink()
        process_source_file("r1", _file(), _source(entities=[
            _entity("inserted", start=1), _entity("alpha", start=15),
            _entity("beta", start=40),
        ]), "file-node", second, "full")

        ids_first = {n.name: n.id for n in first.nodes}
        ids_second = {n.name: n.id for n in second.nodes}
        assert ids_first["alpha"] == ids_second["alpha"]
        assert ids_first["beta"] == ids_second["beta"]

    def test_arity_distinguishes_overloads(self):
        sink = IngestSink()
        process_source_file("r1", _file(), _source(entities=[
            _entity("save", params=["a"]), _entity("save", params=["a", "b"]),
        ]), "file-node", sink, "full")
        methods = [n for n in sink.nodes if n.type == "Method"]
        assert len(methods) == 2
        assert methods[0].id != methods[1].id
        arities = sorted(m.extra_props["arity"] for m in methods)
        assert arities == [1, 2]

    def test_symbol_uid_uses_parent_class(self):
        sink = IngestSink()
        process_source_file("r1", _file(), _source(entities=[
            _entity("run", parent="Worker"),
        ]), "file-node", sink, "full")
        node = next(n for n in sink.nodes if n.type == "Method")
        assert "Worker.run" in node.symbol_uid

    def test_imports_counted_never_emitted(self):
        sink = IngestSink()
        imports = [SimpleNamespace(module=f"m{i}", is_wildcard=False, line=i)
                   for i in range(3)]
        process_source_file("r1", _file(), _source(imports=imports),
                            "file-node", sink, "full")
        assert sink.lang("Java")["imports_unemitted"] == 3
        assert not [n for n in sink.nodes if n.type in ("Import", "Package")]


class TestEndpoints:
    def test_endpoint_dedupe_and_handler_edges(self):
        sink = IngestSink()
        source = _source(
            entities=[_entity("get_user", type_="function", start=5)],
            endpoints=[
                ParsedApiEndpoint(method="get", path="/users/{id}",
                                  handler_name="get_user", controller_name="",
                                  line=5, framework="fastapi"),
                ParsedApiEndpoint(method="GET", path="/users/:id",
                                  handler_name="missing_handler",
                                  controller_name="", line=40,
                                  framework="fastapi"),
            ],
        )
        process_source_file("r1", _file(path="api.py", language="Python"),
                            source, "file-node", sink, "full")
        endpoints = [n for n in sink.nodes if n.type == "ApiEndpoint"]
        assert len(endpoints) == 1

        exposes = [e for e in sink.edges if e.type == "EXPOSES_API"]
        assert len(exposes) == 2
        handler_node = next(n for n in sink.nodes if n.type == "Function")
        sources = {e.source_id for e in exposes}
        assert handler_node.id in sources
        assert "file-node" in sources
        assert all(e.evidence for e in exposes)


class TestArtifacts:
    def test_config_values_redacted(self):
        sink = IngestSink()
        config = ConfigParseResult(entries=[
            ConfigEntry(key="spring.datasource.password",
                        value="PLANTEDSECRETVALUE12345678", file="app.yml",
                        line=3),
            ConfigEntry(key="server.port", value="8080", file="app.yml", line=5),
        ], detected_systems=[])
        process_config("r1", _file(path="app.yml", language="YAML"), config,
                       "file-node", sink)
        blob = json.dumps([vars(n) for n in sink.nodes], default=str)
        assert "PLANTEDSECRETVALUE12345678" not in blob
        secret = next(n for n in sink.nodes
                      if n.name == "spring.datasource.password")
        assert secret.extra_props["value_class"] == "secret"
        declares = [e for e in sink.edges if e.type == "DECLARES"]
        assert len(declares) == 2

    def test_dependency_dedupe_across_manifests(self):
        sink = IngestSink()
        dep = DependencyInfo(name="express", version="4.18.0", scope="prod",
                             source_file="package.json", type="npm")
        process_dependencies("r1", _file(path="package.json"), [dep],
                             "file-a", sink)
        process_dependencies("r1", _file(path="web/package.json"), [dep],
                             "file-b", sink)
        deps = [n for n in sink.nodes if n.type == "Dependency"]
        assert len(deps) == 1
        edges = [e for e in sink.edges if e.type == "DEPENDS_ON"]
        assert len(edges) == 2
        assert deps[0].extra_props["purl"] == "pkg:npm/express@4.18.0"


class TestBuildGraphOnFixtures:
    def test_callgraph_sample_produces_typed_graph(self):
        scan = scan_repository(os.path.join(FIXTURES, "callgraph-sample"))
        sink = build_graph("fixrepo", "fix", "sample",
                            "https://github.com/fix/sample", "main",
                            "deadbeef", scan)
        types = {n.type for n in sink.nodes}
        assert "Repo" in types
        assert "File" in types
        assert {"Method", "Function"} & types
        edge_types = {e.type for e in sink.edges}
        assert "CONTAINS" in edge_types
        assert "DECLARES" in edge_types
        assert "RELATES_TO" not in edge_types
        ids = [n.id for n in sink.nodes]
        assert len(ids) == len(set(ids))
        repo_node = next(n for n in sink.nodes if n.type == "Repo")
        assert repo_node.id == "fixrepo"
        assert repo_node.extra_props["head_commit_sha"] == "deadbeef"
        totals = sum(c["files_parsed"] for c in sink.coverage.values())
        assert totals > 0

    def test_planted_secrets_never_reach_graph(self):
        scan = scan_repository(os.path.join(FIXTURES, "planted-secret"))
        sink = build_graph("secrepo", "sec", "planted",
                            "https://github.com/sec/planted", "main",
                            "cafe1234", scan)
        blob = json.dumps(
            [vars(n) for n in sink.nodes] + [vars(e) for e in sink.edges],
            default=str,
        )
        assert "PLANTEDSECRET" not in blob
        configs = [n for n in sink.nodes if n.type == "Config"]
        assert configs, "planted fixture must produce Config nodes"
        assert any(n.extra_props.get("value_class") == "secret"
                   for n in configs)

    def test_parse_cap_skips_large_files(self, monkeypatch):
        # scan reads the core config, not the server's settings.
        monkeypatch.setattr(
            engine_config, "_active",
            dataclasses.replace(engine_config.get_config(),
                                parse_file_cap_bytes=10))
        scan = scan_repository(os.path.join(FIXTURES, "callgraph-sample"))
        sink = build_graph("caprepo", "cap", "sample",
                            "https://github.com/cap/sample", "main",
                            "beef", scan)
        skipped = sum(c["files_skipped_large"] for c in sink.coverage.values())
        assert skipped > 0
        assert not [n for n in sink.nodes if n.type in ("Method", "Function")]
