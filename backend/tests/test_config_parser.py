import pytest
from tracekite.parsers.config_parser import (
    parse_properties_file,
    parse_yaml_file,
    parse_env_file,
    parse_config_file,
)
from tracekite.parsers.parser_registry import is_config_file


class TestPropertiesParser:
    def test_basic(self):
        content = """
server.port=8080
spring.datasource.url=jdbc:postgresql://localhost:5432/db
# comment
"""
        result = parse_properties_file("application.properties", content)
        keys = {e.key for e in result.entries}
        assert "server.port" in keys
        assert "spring.datasource.url" in keys
        assert "PostgreSQL" in result.detected_systems


class TestYamlParser:
    def test_nested_keys(self):
        content = """
spring:
  application:
    name: gateway-service
server:
  port: 8060
"""
        result = parse_yaml_file("application.yml", content)
        keys = {e.key for e in result.entries}
        assert "spring.application.name" in keys
        assert "server.port" in keys

    def test_list_items(self):
        content = """
spring:
  cloud:
    gateway:
      routes:
      - id: employee-service
        uri: lb://employee-service
        predicates:
        - Path=/employee/**
"""
        result = parse_yaml_file("gateway-service.yml", content)
        keys = {e.key for e in result.entries}
        values = {e.value for e in result.entries}

        assert any("routes[0].id" in k for k in keys)
        assert any("routes[0].uri" in k for k in keys)
        assert "lb://employee-service" in values
        assert "Path=/employee/**" in values
        assert "employee-service" in result.detected_systems

    def test_null_values(self):
        content = """
spring:
  cloud:
    gateway:
      discovery:
        locator:
          enabled:
"""
        result = parse_yaml_file("application.yml", content)
        keys = {e.key for e in result.entries}
        assert "spring.cloud.gateway.discovery.locator.enabled" in keys


class TestEnvParser:
    def test_basic(self):
        content = """
DATABASE_URL=postgres://localhost/db
# comment
DEBUG=true
"""
        result = parse_env_file(".env", content)
        keys = {e.key for e in result.entries}
        assert "DATABASE_URL" in keys
        assert "DEBUG" in keys


class TestConfigDispatch:
    def test_yaml_config_detection(self):
        content = "spring:\n  application:\n    name: test"
        assert is_config_file("application.yml", content)
        assert not is_config_file("deployment.yml", "kind: Deployment\napiVersion: apps/v1")

    def test_config_parser_dispatch(self):
        content = "server:\n  port: 8080"
        result = parse_config_file("application.yml", content)
        keys = {e.key for e in result.entries}
        assert "server.port" in keys
