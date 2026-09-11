"""
Legacy regex-based parser tests.

Covers the original parser modules with sample file contents, aiming for high
line and branch coverage (including empty/error branches).
"""

import pytest
from unittest.mock import patch

from tracekite.parsers.base import ParsedImport, ParseResult
from tracekite.parsers.java_parser import JavaParser
from tracekite.parsers.python_parser import PythonParser
from tracekite.parsers.javascript_parser import JavaScriptParser
from tracekite.parsers.kotlin_parser import KotlinParser
from tracekite.parsers.config_parser import (
    ConfigEntry,
    ConfigParseResult,
    EXTERNAL_SYSTEM_PATTERNS,
    detect_systems_from_dependencies,
    detect_systems_from_imports,
    parse_config_file,
    parse_env_file,
    parse_properties_file,
    parse_yaml_file,
    _extract_yaml_keys,
    _extract_yaml_value,
)
from tracekite.parsers.dependency_parser import (
    DependencyInfo,
    detect_dependency_type,
    parse_build_gradle,
    parse_dependency_file,
    parse_go_mod,
    parse_package_json,
    parse_pom_xml,
    parse_requirements_txt,
)
from tracekite.parsers.docker_parser import (
    DockerResource,
    parse_docker_compose,
    parse_docker_file,
    parse_dockerfile,
)
from tracekite.parsers.kubernetes_parser import (
    K8sResource,
    K8S_KINDS,
    parse_helm_values,
    parse_k8s_file,
    parse_kubernetes_yaml,
)


# -----------------------------------------------------------------------------
# JavaParser
# -----------------------------------------------------------------------------

class TestJavaParser:
    def test_supported_extensions(self):
        assert JavaParser().supported_extensions == [".java"]
        assert JavaParser().can_parse("Foo.java")
        assert not JavaParser().can_parse("Foo.kt")

    def test_parse_full(self):
        code = '''\
package com.example.demo;

import java.util.List;
import static org.junit.Assert.*;

@RestController
@RequestMapping("/api")
public class UserController {
    @GetMapping
    public List<User> getUsers() {
        return null;
    }

    @PostMapping("/{id}")
    public User createUser(@PathVariable Long id) {
        if (id != null) {
            return null;
        }
        return null;
    }
}

interface UserRepository {
    List<User> findAll();
}

enum Status { ACTIVE, INACTIVE }
'''
        parser = JavaParser()
        result = parser.parse("UserController.java", code)

        assert result.package == "com.example.demo"
        assert len(result.imports) == 2
        assert result.imports[1].is_wildcard

        classes = [e for e in result.entities if e.type == "class"]
        assert len(classes) == 1
        assert classes[0].name == "UserController"

        interfaces = [e for e in result.entities if e.type == "interface"]
        assert len(interfaces) == 1

        enums = [e for e in result.entities if e.type == "enum"]
        assert len(enums) == 1

        methods = [e for e in result.entities if e.type == "method"]
        assert {m.name for m in methods} == {"getUsers", "createUser"}
        assert any("@GetMapping" in m.annotations for m in methods)

        # Class-level @RequestMapping is also matched as an ANY endpoint;
        # base_path is not prepended to method paths by this parser.
        assert len(result.api_endpoints) == 3
        post = [ep for ep in result.api_endpoints if ep.method == "POST"][0]
        assert post.path == "/{id}"
        assert post.handler_name == "createUser"

    def test_parse_exception_path(self):
        parser = JavaParser()
        parser._extract_package = lambda content: (_ for _ in ()).throw(ValueError("boom"))
        result = parser.parse("Bad.java", "class Bad {}")
        assert len(result.errors) == 1
        assert "boom" in result.errors[0]

    def test_extract_package_missing(self):
        assert JavaParser()._extract_package("class A {}") == ""

    def test_extract_imports_empty(self):
        assert JavaParser()._extract_imports("class A {}") == []

    def test_class_without_brace_skipped(self):
        code = "class Missing"
        entities = JavaParser()._extract_classes_and_methods(code, code.split("\n"))
        assert entities == []

    def test_method_without_brace_skipped(self):
        code = '''class A {
    void noBrace()
}'''
        entities = JavaParser()._extract_classes_and_methods(code, code.split("\n"))
        methods = [e for e in entities if e.type == "method"]
        assert methods == []

    def test_spring_endpoints_no_controller(self):
        code = '''class NotAController {
    @GetMapping("/users")
    public void list() {}
}'''
        parser = JavaParser()
        result = parser.parse("NotAController.java", code)
        assert result.api_endpoints == []

    @pytest.mark.parametrize("annotation,method,path", [
        ("@GetMapping", "GET", ""),
        ('@GetMapping("/x")', "GET", "/x"),
        ('@GetMapping(value="/y")', "GET", "/y"),
        ("@RequestMapping", "ANY", ""),
        ('@PostMapping("/z")', "POST", "/z"),
    ])
    def test_spring_mapping_variants(self, annotation, method, path):
        code = f'''@RestController
@RequestMapping("/api")
public class C {{
    {annotation}
    public void handle() {{ if (true) {{}} }}
}}'''
        parser = JavaParser()
        result = parser.parse("C.java", code)
        # Method-level endpoint is present (class-level @RequestMapping is also matched)
        eps = [ep for ep in result.api_endpoints if ep.handler_name == "handle"]
        assert len(eps) >= 1
        assert any(e.method == method and e.path == path for e in eps)

    def test_extract_annotations_stops_on_code(self):
        parser = JavaParser()
        content = '''@Service
@Deprecated
public class A {
    @Override
    void run() {}
}'''
        anns = parser._extract_annotations(content, content.find("class A"))
        assert anns == ["@Service", "@Deprecated"]

    def test_find_matching_brace_unbalanced(self):
        parser = JavaParser()
        assert parser._find_matching_brace("{abc", 0) == -1

    def test_constructor_skipped(self):
        code = '''public class UserController {
    public UserController() {}
    public void handle() { if (true) {} }
}'''
        result = JavaParser().parse("UserController.java", code)
        methods = [e.name for e in result.entities if e.type == "method"]
        assert "UserController" not in methods
        assert "handle" in methods

    def test_request_mapping_before_rest_controller(self):
        code = '''@RequestMapping("/api")
@RestController
public class C {
    @GetMapping
    public void handle() { if (true) {} }
}'''
        result = JavaParser().parse("C.java", code)
        assert any(ep.method == "GET" and ep.path == "/api" for ep in result.api_endpoints)


# -----------------------------------------------------------------------------
# PythonParser
# -----------------------------------------------------------------------------

class TestPythonParser:
    def test_supported_extensions(self):
        assert PythonParser().supported_extensions == [".py"]

    def test_parse_full(self):
        code = '''\
import os, sys
from typing import List
from fastapi import FastAPI
from starlette.requests import Request

app = FastAPI()

@app.get("/users")
def list_users() -> List[dict]:
    return []

class UserService:
    def __init__(self):
        self.users = []

    def get_user(self, user_id: int):
        return self.users[user_id]
'''
        parser = PythonParser()
        result = parser.parse("app.py", code)

        modules = {i.module for i in result.imports}
        assert "os" in modules
        assert "sys" in modules
        assert "typing" in modules
        assert "fastapi" in modules

        classes = [e for e in result.entities if e.type == "class"]
        assert len(classes) == 1
        assert classes[0].name == "UserService"

        methods = [e for e in result.entities if e.type == "method"]
        assert {m.name for m in methods} == {"__init__", "get_user"}

        functions = [e for e in result.entities if e.type == "function"]
        assert {f.name for f in functions} == {"list_users"}

        assert len(result.api_endpoints) == 1
        assert result.api_endpoints[0].method == "GET"
        assert result.api_endpoints[0].path == "/users"

    def test_parse_exception_path(self):
        parser = PythonParser()
        parser._extract_imports = lambda content: (_ for _ in ()).throw(RuntimeError("boom"))
        result = parser.parse("bad.py", "x = 1")
        assert "boom" in result.errors[0]

    @pytest.mark.parametrize("method", ["get", "post", "put", "delete", "patch", "head", "options"])
    def test_fastapi_methods(self, method):
        code = f'''@app.{method}("/items")
def handle():
    pass
'''
        result = PythonParser().parse("routes.py", code)
        assert len(result.api_endpoints) == 1
        assert result.api_endpoints[0].method == method.upper()

    def test_flask_routes(self):
        code = '''@app.route("/items", methods=["POST", "GET"])
def create_item():
    pass

@app.route("/simple")
def simple():
    pass
'''
        result = PythonParser().parse("flask_app.py", code)
        methods = {ep.method for ep in result.api_endpoints}
        paths = {ep.path for ep in result.api_endpoints}
        assert methods == {"POST", "GET"}
        assert paths == {"/items", "/simple"}

    def test_api_endpoint_unknown_handler(self):
        code = '@app.get("/orphan")\n'
        result = PythonParser().parse("orphan.py", code)
        assert result.api_endpoints[0].handler_name == "unknown"

    def test_top_level_def_skips_indented_methods(self):
        code = '''class A:
    def inside(self):
        pass

def outside():
    pass
'''
        result = PythonParser().parse("mix.py", code)
        funcs = [e.name for e in result.entities if e.type == "function"]
        assert "outside" in funcs
        assert "inside" not in funcs

    def test_find_block_end_edge_cases(self):
        parser = PythonParser()
        # _find_block_end starts at the declaration line itself, so an empty
        # or comment-only body collapses back to the declaration line.
        assert parser._find_block_end("def a():\n", 0) == 1
        assert parser._find_block_end("def a():\n    # c\n", 0) == 1
        # With a body present but no dedent found, the last line is returned.
        assert parser._find_block_end("def a():\n    pass\n", 0) == 3
        assert parser._find_block_end("def a():", 0) == 1

    def test_extract_decorators_break_on_code(self):
        parser = PythonParser()
        content = '''@router.get("/x")
x = 1
@app.get("/y")
def a():
    pass
'''
        anns = parser._extract_decorators(content, content.find("def a"))
        # The non-comment, non-annotation line stops the decorator scan.
        assert anns == ["@router.get"]


# -----------------------------------------------------------------------------
# JavaScriptParser
# -----------------------------------------------------------------------------

class TestJavaScriptParser:
    def test_supported_extensions(self):
        assert ".tsx" in JavaScriptParser().supported_extensions

    def test_parse_full(self):
        code = '''import React from 'react';
import { useState } from 'react';
import * as api from './api';
const helper = require('./helper');

export class UserStore {
    getUsers() {
        return [];
    }
}

export async function fetchData() {
    return null;
}

const UserCard = () => {
    return <div/>;
};

function Welcome() {
    return <h1/>;
}

app.get('/users', (req, res) => res.json([]));

export async function GET(request) {
    return Response.json({});
}
'''
        parser = JavaScriptParser()
        result = parser.parse("App.jsx", code)

        modules = {i.module for i in result.imports}
        assert "react" in modules
        assert "./api" in modules
        assert "./helper" in modules

        names = {e.name: e.type for e in result.entities}
        assert names["UserStore"] == "class"
        assert names["fetchData"] == "function"
        assert names["UserCard"] == "component"
        assert names["Welcome"] == "component"
        assert "getUsers" in {e.name for e in result.entities if e.type == "method"}

        ep_paths = {ep.path for ep in result.api_endpoints}
        assert "/users" in ep_paths
        # App Router handlers are NOT this parser's to extract: their path
        # comes from the directory, which content-only parsing cannot see.
        # The old branch emitted the literal placeholder "/api/..." as the
        # path — this assertion used to PIN that fabrication.
        assert not any(ep.framework == "Next.js App Router"
                       for ep in result.api_endpoints)
        assert not any("..." in ep.path for ep in result.api_endpoints)

    def test_parse_exception_path(self):
        parser = JavaScriptParser()
        parser._extract_imports = lambda content: (_ for _ in ()).throw(TypeError("boom"))
        result = parser.parse("bad.js", "x = 1")
        assert "boom" in result.errors[0]

    def test_arrow_function_filter(self):
        code = '''const a = () => { return 1; };
const App = () => { return <div/>; };
'''
        result = JavaScriptParser().parse("x.jsx", code)
        names = {e.name for e in result.entities}
        assert "a" not in names
        assert "App" in names

    def test_extract_methods_skip_control_keywords(self):
        code = '''class A {
    if(x) {}
    while(x) {}
    realMethod() {}
}'''
        methods = JavaScriptParser()._extract_methods(code, 1)
        assert [m.name for m in methods] == ["realMethod"]

    def test_find_brace_end_no_brace(self):
        parser = JavaScriptParser()
        assert parser._find_brace_end("function a()", 0) == 1

    def test_find_brace_end_with_strings(self):
        parser = JavaScriptParser()
        code = 'function a() { const s = "}"; return "{"; }'
        assert parser._find_brace_end(code, 0) == 1

    def test_nextjs_framework_detection(self):
        code = '''import next from 'next';
app.get('/api/hello', (req, res) => {});
'''
        result = JavaScriptParser().parse("pages/api/hello.js", code)
        assert all(ep.framework == "Next.js" for ep in result.api_endpoints)


# -----------------------------------------------------------------------------
# KotlinParser
# -----------------------------------------------------------------------------

class TestKotlinParser:
    def test_supported_extensions(self):
        assert KotlinParser().supported_extensions == [".kt"]

    def test_parse_full(self):
        code = '''package com.example

import org.springframework.web.bind.annotation.*

@RestController
@RequestMapping("/api")
class UserController {
    @GetMapping("/users")
    fun getUsers(): List<String> {
        return listOf()
    }
}

interface UserRepository {
    fun findAll(): List<String>
}

object Config {
    val port = 8080
}

fun helper() = Unit
'''
        parser = KotlinParser()
        result = parser.parse("Controller.kt", code)

        assert result.package == "com.example"
        assert result.imports[0].is_wildcard

        types = {e.name: e.type for e in result.entities}
        assert types["UserController"] == "class"
        assert types["UserRepository"] == "interface"
        assert types["Config"] == "object"
        assert types["helper"] == "function"

        methods = [e for e in result.entities if e.type == "method"]
        assert {m.name for m in methods} == {"getUsers", "findAll"}

        # Class-level @RequestMapping creates an ANY endpoint as well.
        # The base path is not prepended to method paths by this parser.
        assert len(result.api_endpoints) == 2
        get_ep = [ep for ep in result.api_endpoints if ep.method == "GET"][0]
        assert get_ep.path == "/users"
        assert get_ep.handler_name == "getUsers"

    def test_parse_exception_path(self):
        parser = KotlinParser()
        parser._extract_package = lambda content: (_ for _ in ()).throw(ValueError("boom"))
        result = parser.parse("bad.kt", "class Bad")
        assert "boom" in result.errors[0]

    def test_top_level_function_filter(self):
        code = '''class A {
    fun inside() {}
}
fun outside() {}
'''
        result = KotlinParser().parse("mix.kt", code)
        funcs = [e.name for e in result.entities if e.type == "function"]
        assert "outside" in funcs

    def test_find_brace_end_string_interpolation(self):
        parser = KotlinParser()
        code = 'class A { val s = "${foo()}" }'
        assert parser._find_brace_end(code, 0) == 1

    def test_spring_endpoints_no_controller(self):
        code = '''class C {
    @GetMapping("/x")
    fun x() {}
}'''
        result = KotlinParser().parse("C.kt", code)
        assert result.api_endpoints == []

    def test_spring_base_path(self):
        code = '''@RequestMapping("/api")
@RestController
class C {
    @GetMapping("/users")
    fun users() {}
}'''
        result = KotlinParser().parse("C.kt", code)
        assert any(ep.method == "GET" and ep.path == "/api/users" for ep in result.api_endpoints)

    def test_kotlin_annotations_immediate_preceding(self):
        parser = KotlinParser()
        content = '''@Service
class A {
    @Transactional
    fun x() {}
}'''
        entities = parser.parse("A.kt", content).entities
        cls = [e for e in entities if e.type == "class"][0]
        mth = [e for e in entities if e.type == "method"][0]
        assert cls.annotations == ["@Service"]
        assert mth.annotations == ["@Transactional"]


# -----------------------------------------------------------------------------
# ConfigParser
# -----------------------------------------------------------------------------

class TestConfigParser:
    def test_parse_properties_basic(self):
        content = '''
server.port=8080
# comment

spring.datasource.url=jdbc:postgresql://localhost:5432/db
spring.redis.host=localhost
key without equals
'''
        result = parse_properties_file("app.properties", content)
        keys = {e.key for e in result.entries}
        assert "server.port" in keys
        assert "spring.datasource.url" in keys
        assert "spring.redis.host" in keys
        assert "key without equals" not in keys
        assert "PostgreSQL" in result.detected_systems
        assert "Redis" in result.detected_systems

    def test_parse_yaml_nested_and_lists(self):
        content = '''
spring:
  application:
    name: gateway
server:
  port: 8080
routes:
  - id: svc
    uri: lb://employee-service
    host: https://api.example.com:443
'''
        result = parse_yaml_file("app.yml", content)
        keys = {e.key for e in result.entries}
        assert "spring.application.name" in keys
        assert "server.port" in keys
        assert any("routes[0].id" in k for k in keys)
        assert any("routes[0].uri" in k for k in keys)
        assert "employee-service" in result.detected_systems
        assert "api.example.com:443" in result.detected_systems

    def test_parse_yaml_null_value(self):
        content = 'top:\n  child:\n'
        result = parse_yaml_file("app.yml", content)
        keys = {e.key for e in result.entries}
        assert "top.child" in keys

    def test_parse_yaml_external_system(self):
        content = 'spring:\n  datasource:\n    url: jdbc:postgresql://localhost/db\n'
        result = parse_yaml_file("app.yml", content)
        assert "PostgreSQL" in result.detected_systems

    def test_parse_yaml_error(self):
        result = parse_yaml_file("bad.yml", "bad: [")
        assert len(result.errors) == 1
        assert result.entries == []

    def test_extract_yaml_keys_list_top_level(self):
        result = ConfigParseResult()
        _extract_yaml_keys([1, {"a": 2}], "", "f.yml", result)
        keys = {e.key for e in result.entries}
        assert "[0]" in keys
        assert "[1].a" in keys

    def test_extract_yaml_value_scalar_branches(self):
        result = ConfigParseResult()
        _extract_yaml_value("k", None, "f.yml", result)
        _extract_yaml_value("k", 42, "f.yml", result)
        _extract_yaml_value("k", True, "f.yml", result)
        assert result.entries[0].value == ""
        assert result.entries[1].value == "42"
        assert result.entries[2].value == "True"

    def test_parse_env_basic_and_variants(self):
        content = '''
DATABASE_URL=postgres://localhost/db
# comment

DEBUG=true
'''
        for name in (".env", ".env.example", ".env.local"):
            result = parse_env_file(name, content)
            keys = {e.key for e in result.entries}
            assert "DATABASE_URL" in keys
            assert "DEBUG" in keys

    def test_detect_systems_from_imports(self):
        imports = [ParsedImport(module="redis")]
        assert "Redis" in detect_systems_from_imports(imports)
        assert "Redis" in detect_systems_from_imports(["redis"])

    def test_detect_systems_from_dependencies(self):
        deps = [DependencyInfo(name="kafka-clients")]
        assert "Kafka" in detect_systems_from_dependencies(deps)
        assert "Kafka" in detect_systems_from_dependencies(["kafka-clients"])

    def test_parse_config_file_dispatch(self):
        assert parse_config_file("app.yml", "server:\n  port: 1").entries
        assert parse_config_file(".env.example", "X=1").entries
        assert parse_config_file("unknown.bin", "x").entries == []

    def test_parse_config_file_exception(self):
        with patch.dict("tracekite.parsers.config_parser.CONFIG_PARSERS", {".yml": lambda fp, c: (_ for _ in ()).throw(IOError("fail"))}):
            result = parse_config_file("app.yml", "server:\n  port: 1")
        assert result.entries == []


# -----------------------------------------------------------------------------
# DependencyParser
# -----------------------------------------------------------------------------

class TestDependencyParser:
    def test_parse_package_json(self):
        content = '''{
            "name": "app",
            "dependencies": {"react": "^18"},
            "devDependencies": {"jest": "^29"},
            "peerDependencies": {"foo": ">=1"}
        }'''
        deps = parse_package_json("package.json", content)
        assert len(deps) == 3
        assert {d.scope for d in deps} == {"dependencies", "devDependencies", "peerDependencies"}
        assert deps[0].type == "npm"

    def test_parse_package_json_invalid(self):
        deps = parse_package_json("package.json", "not json")
        assert deps == []

    def test_parse_requirements_txt(self):
        content = '''
requests==2.28.1
fastapi>=0.100.0
numpy
# comment
pytest~=7.0
-r req.txt
'''
        deps = parse_requirements_txt("requirements.txt", content)
        by_name = {d.name: d for d in deps}
        assert by_name["requests"].version == "2.28.1"
        assert by_name["fastapi"].version == "0.100.0"
        assert by_name["numpy"].version == ""
        assert by_name["pytest"].version == "7.0"

    def test_parse_pom_xml(self):
        content = '''<?xml version="1.0"?>
<project>
    <dependency>
        <groupId>g</groupId>
        <artifactId>a</artifactId>
        <version>1</version>
    </dependency>
    <dependency>
        <groupId>g2</groupId>
        <artifactId>a2</artifactId>
        <scope>test</scope>
    </dependency>
</project>'''
        deps = parse_pom_xml("pom.xml", content)
        assert len(deps) == 2
        assert deps[0].name == "g:a"
        assert deps[0].version == "1"
        assert deps[1].scope == "test"

    def test_parse_pom_xml_exception(self):
        with patch("tracekite.parsers.dependency_parser.re.finditer", side_effect=RuntimeError("boom")):
            deps = parse_pom_xml("pom.xml", "<x/>")
        assert deps == []

    def test_parse_build_gradle(self):
        content = '''
dependencies {
    implementation 'org:x:1.0'
    api "org:y:2.0"
    compileOnly 'short'
    testImplementation 'a:b:3.0'
}
'''
        deps = parse_build_gradle("build.gradle", content)
        by_name = {d.name: d for d in deps}
        assert "org:x:1.0" in by_name
        assert "org:y:2.0" in by_name
        assert "short" not in by_name
        assert by_name["a:b:3.0"].version == "3.0"

    def test_parse_go_mod_block(self):
        content = '''module example

go 1.21

require (
    github.com/a/b v1.0.0
    github.com/c/d v2.0.0
)
'''
        deps = parse_go_mod("go.mod", content)
        assert len(deps) == 2
        assert deps[0].name == "github.com/a/b"

    def test_parse_go_mod_no_block(self):
        content = '''module example
require github.com/a/b v1.0.0
'''
        deps = parse_go_mod("go.mod", content)
        assert len(deps) == 1

    def test_parse_dependency_file_dispatch(self):
        assert parse_dependency_file("package.json", '{"dependencies":{"x":"1"}}')
        assert parse_dependency_file("unknown.txt", "x") == []

    def test_parse_dependency_file_exception(self):
        with patch.dict("tracekite.parsers.dependency_parser.DEPENDENCY_PARSERS", {"requirements.txt": lambda fp, c: (_ for _ in ()).throw(IOError("fail"))}):
            deps = parse_dependency_file("requirements.txt", "x")
        assert deps == []

    def test_detect_dependency_type(self):
        assert detect_dependency_type("package.json") == "npm"
        assert detect_dependency_type("pom.xml") == "maven"
        assert detect_dependency_type("unknown") is None


# -----------------------------------------------------------------------------
# DockerParser
# -----------------------------------------------------------------------------

class TestDockerParser:
    def test_parse_dockerfile(self):
        content = '''FROM node:18
EXPOSE 3000 3001
ENV PORT=3000
# comment

FROM alpine:latest
EXPOSE 8080
'''
        resources = parse_dockerfile("Dockerfile", content)
        images = [r for r in resources if r.type == "image"]
        assert len(images) == 2
        assert images[0].image == "node:18"
        assert images[0].ports == ["3000", "3001"]
        assert images[0].env_vars == ["PORT"]
        assert images[1].image == "alpine:latest"
        assert images[1].ports == ["8080"]
        assert any(r.type == "dockerfile" for r in resources)

    def test_parse_dockerfile_no_from(self):
        resources = parse_dockerfile("Dockerfile", "# empty\n")
        assert len(resources) == 1
        assert resources[0].type == "dockerfile"
        assert resources[0].image == ""

    def test_parse_docker_compose(self):
        content = '''
services:
  web:
    image: nginx
    ports:
      - "80:80"
    environment:
      DEBUG: "true"
volumes:
  data: {}
networks:
  backend:
'''
        resources = parse_docker_compose("docker-compose.yml", content)
        by_type = {}
        for r in resources:
            by_type.setdefault(r.type, []).append(r)
        assert any(r.name == "web" and r.image == "nginx" for r in by_type["service"])
        assert any(r.name == "data" for r in by_type["volume"])
        assert any(r.name == "backend" for r in by_type["network"])

    def test_parse_docker_compose_volumes_list(self):
        content = '''
services:
  app:
    image: app
volumes:
  - data
'''
        resources = parse_docker_compose("docker-compose.yml", content)
        volumes = [r for r in resources if r.type == "volume"]
        assert volumes[0].name == "data"

    def test_parse_docker_compose_invalid_yaml(self):
        resources = parse_docker_compose("docker-compose.yml", "bad: [")
        assert resources == []

    def test_parse_docker_compose_non_dict(self):
        resources = parse_docker_compose("docker-compose.yml", "just a string")
        assert resources == []

    def test_parse_docker_file_dispatch(self):
        assert parse_docker_file("Dockerfile", "FROM x")
        assert parse_docker_file("x.dockerfile", "FROM x")
        compose = "services:\n  app:\n    image: x\n"
        assert parse_docker_file("docker-compose.yml", compose)
        assert parse_docker_file("other.yml", "") == []


# -----------------------------------------------------------------------------
# KubernetesParser
# -----------------------------------------------------------------------------

class TestKubernetesParser:
    def test_parse_kubernetes_yaml(self):
        content = '''
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: prod
  labels:
    app: web
---
apiVersion: v1
kind: Service
metadata:
  name: web-svc
'''
        resources = parse_kubernetes_yaml("deploy.yml", content)
        assert len(resources) == 2
        assert resources[0].kind == "Deployment"
        assert resources[0].namespace == "prod"
        assert resources[0].labels == {"app": "web"}
        assert resources[1].kind == "Service"
        assert resources[1].namespace == "default"

    def test_parse_kubernetes_yaml_skips_unknown_and_non_dict(self):
        content = '''
kind: UnknownKind
metadata:
  name: x
---
not a mapping
'''
        resources = parse_kubernetes_yaml("mixed.yml", content)
        assert resources == []

    def test_parse_kubernetes_yaml_error(self):
        resources = parse_kubernetes_yaml("bad.yml", "bad: [")
        assert resources == []

    def test_parse_helm_values(self):
        content = 'name: my-chart\nimage: nginx\n'
        resources = parse_helm_values("values.yaml", content)
        assert len(resources) == 1
        assert resources[0].kind == "HelmValues"
        assert resources[0].name == "my-chart"

    def test_parse_helm_values_invalid_yaml(self):
        resources = parse_helm_values("values.yaml", "bad: [")
        assert resources == []

    def test_parse_k8s_file_dispatch(self):
        assert parse_k8s_file("values.yaml", "name: x")
        assert parse_k8s_file("Chart.yaml", "name: x")
        assert parse_k8s_file("deploy.yml", "kind: Deployment\nmetadata:\n  name: x")
