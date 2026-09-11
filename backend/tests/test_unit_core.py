"""Unit tests: hashing identity, redaction, canonical keys, graph factories."""

import json

import pytest

from tracekite import engine_config
from tracekite.config import settings
from tracekite.services import graph_factories as gf
from tracekite.services.redaction import (
    RedactionKeyMissing, is_secret_key, redact, shannon_entropy_bits,
)
from tracekite.utils import hashing
from tracekite.utils.canonical import (
    build_purl, canonicalize_path_template, normalize_http_method,
)


class TestHashing:
    def test_node_id_deterministic_with_typed_prefix(self):
        a = hashing.generate_node_id("r1", "File", "src/App.java")
        b = hashing.generate_node_id("r1", "File", "src/App.java")
        assert a == b
        prefix, type_part, digest = a.split(":")
        assert (prefix, type_part) == ("r1", "File")
        assert len(digest) == 16
        int(digest, 16)

    def test_node_id_varies_by_inputs(self):
        base = hashing.generate_node_id("r1", "File", "src/App.java")
        assert hashing.generate_node_id("r2", "File", "src/App.java") != base
        assert hashing.generate_node_id("r1", "Class", "src/App.java") != base
        assert hashing.generate_node_id("r1", "File", "src/Other.java") != base

    def test_symbol_extra_has_no_line_numbers(self):
        extra = hashing.symbol_extra("process", 2, 0)
        assert extra.endswith(":0")
        assert extra == hashing.symbol_extra("process", 2, 0)
        assert extra != hashing.symbol_extra("process", 2, 1)
        assert extra != hashing.symbol_extra("process", 3, 0)

    def test_symbol_uid_carries_identity(self):
        uid = hashing.build_symbol_uid("r1", "java", "src/App.java",
                                       "App.process", 2)
        assert "src/App.java" in uid
        assert "App.process" in uid
        assert "2" in uid

    def test_normalize_github_url_variants(self):
        for url in ("https://github.com/foo/bar",
                    "https://github.com/foo/bar.git",
                    "https://github.com/foo/bar/"):
            normalized, owner, repo = hashing.normalize_github_url(url)
            assert owner == "foo"
            assert repo == "bar"
            assert normalized.startswith("https://github.com/foo/bar")

    def test_normalize_github_url_rejects_garbage(self):
        with pytest.raises(ValueError):
            hashing.normalize_github_url("not-a-url")

    def test_extract_git_host(self):
        assert hashing.extract_git_host("https://gitlab.com/x/y") == "gitlab.com"

    def test_repo_id_stable(self):
        assert hashing.generate_repo_id("foo", "bar") == \
            hashing.generate_repo_id("foo", "bar")

    def test_sanitize_path_blocks_traversal(self):
        cleaned = hashing.sanitize_path("../../etc/passwd")
        assert ".." not in cleaned


class TestRedaction:
    def test_denylisted_key_is_secret(self):
        value = "correct-horse-battery"
        result = redact("DB_PASSWORD", value)
        props = result.to_props()
        assert props["value_class"] == "secret"
        assert value not in json.dumps(props)
        assert len(props["value_hmac"]) == 16

    def test_high_entropy_value_is_secret(self):
        value = "aB9xQ2mZ7kP4wR8tY3nV6cJ1"
        assert shannon_entropy_bits(value) >= 4.0
        result = redact("some_setting", value)
        assert result.value_class == "secret"
        assert value not in json.dumps(result.to_props())

    def test_url_classification_keeps_shape_only(self):
        result = redact("service.url", "https://api.example.com:8443/v1/things")
        props = result.to_props()
        assert props["value_class"] == "url"
        assert props["value_host"] == "api.example.com"
        assert props["value_scheme"] == "https"
        assert props["value_port"] == 8443
        assert "things" not in json.dumps(props).replace("/v1", "")

    def test_scalar_classes(self):
        assert redact("flag", "true").value_class == "bool"
        assert redact("server.port", "8080").value_class == "port"
        assert redact("count", "123456789").value_class == "number"
        assert redact("profile", "production").value_class == "enum-ish"

    def test_hmac_deterministic_and_distinct(self):
        first = redact("k", "value-one")
        second = redact("k", "value-one")
        third = redact("k", "value-two")
        assert first.value_hmac == second.value_hmac
        assert first.value_hmac != third.value_hmac

    def test_missing_hmac_key_raises(self, monkeypatch):
        """Redaction reads the core config, not the server's settings — an
        unconfigured engine must refuse to hash rather than hash under ''."""
        monkeypatch.setattr(engine_config, "_active",
                            engine_config.EngineConfig())
        with pytest.raises(RedactionKeyMissing):
            redact("k", "some-value")

    def test_is_secret_key_denylist(self):
        for key in ("password", "API_KEY", "spring.datasource.password",
                    "AUTH_TOKEN", "private_key"):
            assert is_secret_key(key), key
        assert not is_secret_key("server.port")


class TestCanonical:
    @pytest.mark.parametrize("raw,expected", [
        ("/users/{id}", "/users/{}"),
        ("/users/:id/orders", "/users/{}/orders"),
        ("/files/<int:file_id>", "/files/{}"),
        ("/env/${var}", "/env/{}"),
        ("/wild/*", "/wild/{}"),
        ("/v1/api//double", "/v1/api/double"),
        ("https://host.com/api/x", "/api/x"),
        ("", "/"),
        ("no-slash", "/no-slash"),
    ])
    def test_path_templates(self, raw, expected):
        assert canonicalize_path_template(raw) == expected

    def test_methods(self):
        assert normalize_http_method("get") == "GET"
        assert normalize_http_method(" post ") == "POST"
        assert normalize_http_method("bogus") == "GET"
        assert normalize_http_method("") == "GET"

    def test_purls(self):
        assert build_purl("maven", "org.spring:core", "6.1") == \
            "pkg:maven/org.spring/core@6.1"
        assert build_purl("npm", "express", "4.18.0") == "pkg:npm/express@4.18.0"
        assert build_purl("pip", "flask", "3.0") == "pkg:pypi/flask@3.0"
        assert build_purl("go", "github.com/gin-gonic/gin", "") == \
            "pkg:golang/github.com/gin-gonic/gin"
        assert build_purl("maven", "org.x:lib", "${revision}") == \
            "pkg:maven/org.x/lib"
        assert build_purl("mystery", "thing", "1") == "pkg:generic/thing@1"


class TestFactories:
    def test_endpoint_id_from_canonical_template(self):
        one = gf.create_endpoint_node("r1", "src/a.py", "Python", "get",
                                      "/users/{id}", "fastapi", "get_user",
                                      "", 10)
        two = gf.create_endpoint_node("r1", "src/a.py", "Python", "GET",
                                      "/users/:id", "fastapi", "other_handler",
                                      "", 99)
        assert one.id == two.id
        assert one.extra_props["http_method"] == "GET"
        assert one.extra_props["path_template"] == "/users/{}"

    def test_dependency_id_is_name_keyed(self):
        one = gf.create_dependency_node("r1", "express", "4.18.0", "prod",
                                        "npm", "package.json")
        two = gf.create_dependency_node("r1", "express", "4.18.0", "prod",
                                        "npm", "apps/web/package.json")
        assert one.id == two.id
        assert one.extra_props["purl"] == "pkg:npm/express@4.18.0"

    def test_config_node_only_redacted_props(self):
        redacted = redact("DB_PASSWORD", "super-secret-value-123456")
        node = gf.create_config_node("r1", "app.yml", "DB_PASSWORD", redacted)
        allowed = {"key", "value_class", "value_hmac", "value_len", "value_host",
                   "value_port", "value_scheme", "value_path_prefix"}
        assert set(node.extra_props).issubset(allowed)
        assert "super-secret-value-123456" not in json.dumps(node.extra_props)

    def test_calls_edge_full_envelope(self):
        edge = gf.create_calls_edge("r1", "a", "b", 0.9,
                                    ["src/x.py:10", "e2", "e3", "e4", "e5", "e6"])
        assert edge.type == "CALLS"
        assert edge.confidence == 0.9
        assert edge.origin == "inferred"
        assert edge.detected_by == "call_graph_resolver"
        assert len(edge.evidence) == 5
        assert not edge.is_lite()

    def test_contains_edge_is_lite(self):
        edge = gf.create_contains_edge("r1", "a", "b")
        assert edge.type == "CONTAINS"
        assert edge.is_lite()

    def test_repo_node_identity(self):
        node = gf.create_repo_node("repoid", "foo", "bar",
                                   "https://github.com/foo/bar", "main",
                                   "abc123", {"Java": 10})
        assert node.id == "repoid"
        assert node.extra_props["head_commit_sha"] == "abc123"
        assert json.loads(node.extra_props["language_summary"]) == {"Java": 10}


class TestReaderHelpers:
    def test_node_from_props_folds_temporal_values_json_safe(self):
        from neo4j.time import DateTime

        from tracekite.services.graph_reader import _node_from_props

        node = _node_from_props({
            "id": "x", "type": "Repo", "name": "r",
            "custom_ts": DateTime(2026, 7, 26, 1, 2, 3),
            "tags": ["a", "b"],
            "plain": 7,
        })
        assert node.metadata["custom_ts"].startswith("2026-07-26T01:02:03")
        assert node.metadata["tags"] == ["a", "b"]
        assert node.metadata["plain"] == 7
