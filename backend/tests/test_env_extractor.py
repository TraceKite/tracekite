"""Env-var read sites across languages."""

import pytest

from evigraph.services.env_extractor import (
    extract_env_reads, extract_shell_interpolations, is_generic_env,
    looks_like_endpoint_var,
)


def names(content, language):
    return sorted(r.name for r in extract_env_reads(content, language))


class TestJavaScript:
    @pytest.mark.parametrize("language", ["javascript", "typescript"])
    def test_all_js_idioms(self, language):
        content = """
const a = process.env.ORDERS_URL;
const b = process.env["VETS_HOST"];
const c = import.meta.env.VITE_API_BASE;
const d = Deno.env.get("PAYMENTS_ENDPOINT");
"""
        assert names(content, language) == [
            "ORDERS_URL", "PAYMENTS_ENDPOINT", "VETS_HOST", "VITE_API_BASE"]


class TestPython:
    def test_all_python_idioms(self):
        content = """
import os
from os import environ
a = os.environ["ORDERS_URL"]
b = os.environ.get("VETS_HOST")
c = os.getenv("PAYMENTS_ENDPOINT")
d = environ["SEARCH_HOST"]
"""
        assert names(content, "python") == [
            "ORDERS_URL", "PAYMENTS_ENDPOINT", "SEARCH_HOST", "VETS_HOST"]


class TestJvm:
    @pytest.mark.parametrize("language", ["java", "kotlin", "scala"])
    def test_jvm_idioms(self, language):
        content = """
String a = System.getenv("ORDERS_URL");
@Value("${vets.service.url:http://localhost}")
private String vetsUrl;
String c = env.getProperty("payments.endpoint");
"""
        assert names(content, language) == [
            "ORDERS_URL", "payments.endpoint", "vets.service.url"]

    def test_value_annotation_default_is_stripped(self):
        [read] = [r for r in extract_env_reads(
            '@Value("${orders.url:http://fallback:8080}")', "java")]
        assert read.name == "orders.url"


class TestGo:
    def test_go_idioms(self):
        content = '''
a := os.Getenv("ORDERS_URL")
b, ok := os.LookupEnv("VETS_HOST")
c := viper.GetString("payments.endpoint")
'''
        assert names(content, "go") == [
            "ORDERS_URL", "VETS_HOST", "payments.endpoint"]


class TestCSharp:
    @pytest.mark.parametrize("language", ["c#", "csharp"])
    def test_csharp_idioms(self, language):
        content = '''
var a = Environment.GetEnvironmentVariable("ORDERS_URL");
var b = _configuration["Vets:Host"];
var c = Configuration.GetValue<string>("Payments:Endpoint");
'''
        assert names(content, language) == [
            "ORDERS_URL", "Payments:Endpoint", "Vets:Host"]


class TestRuby:
    def test_ruby_idioms(self):
        content = '''
a = ENV["ORDERS_URL"]
b = ENV.fetch("VETS_HOST")
'''
        assert names(content, "ruby") == ["ORDERS_URL", "VETS_HOST"]


class TestBehaviour:
    def test_unknown_language_yields_nothing(self):
        assert extract_env_reads('process.env.X', "cobol") == []
        assert extract_env_reads('process.env.X', None) == []

    def test_duplicates_collapse_to_first_occurrence(self):
        content = "a = process.env.ORDERS_URL\nb = process.env.ORDERS_URL\n"
        reads = extract_env_reads(content, "javascript")
        assert len(reads) == 1
        assert reads[0].line == 1

    def test_line_numbers_are_reported(self):
        content = "\n\nconst x = process.env.ORDERS_URL;\n"
        assert extract_env_reads(content, "javascript")[0].line == 3

    def test_generic_names_flagged(self):
        reads = {r.name: r.generic for r in extract_env_reads(
            'a=process.env.PATH; b=process.env.ORDERS_URL', "javascript")}
        assert reads["PATH"] is True
        assert reads["ORDERS_URL"] is False

    @pytest.mark.parametrize("name", ["PATH", "HOME", "NODE_ENV", "PORT",
                                      "LOG_LEVEL", "DEBUG"])
    def test_generic_denylist(self, name):
        assert is_generic_env(name) is True

    @pytest.mark.parametrize("name,expected", [
        ("ORDERS_URL", True), ("VETS_HOST", True), ("KAFKA_BOOTSTRAP", True),
        ("SQS_QUEUE_NAME", True), ("SEARCH_ENDPOINT", True),
        ("DB_CONNECTION_STRING", True), ("PAYMENTS_SERVICE", True),
        ("RETRY_COUNT", False), ("MAX_THREADS", False), ("FEATURE_X", False),
    ])
    def test_endpoint_like_ranking(self, name, expected):
        # Ranks which unresolved variables are worth surfacing: an unresolved
        # *_URL is a missing edge, an unresolved RETRY_COUNT is not.
        assert looks_like_endpoint_var(name) is expected


class TestShellInterpolation:
    def test_config_placeholders(self):
        content = "url: ${ORDERS_URL}\nhost: ${VETS_HOST:-localhost}\n"
        assert sorted(r.name for r in extract_shell_interpolations(content)) == [
            "ORDERS_URL", "VETS_HOST"]

    def test_non_placeholder_text_ignored(self):
        assert extract_shell_interpolations("cost: $100 and {braces}") == []
