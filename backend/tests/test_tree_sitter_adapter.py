"""
Unit and integration tests for adduce.parsers.tree_sitter.adapter.

Covers:
- TreeSitterSourceParser.parse() for every supported language.
- Endpoint extraction branches (Spring, FastAPI, Flask, Express, Gin, stdlib Go, Actix, Axum).
- Import extraction for Java/Kotlin, Python, JavaScript/TypeScript, and Go.
- Error paths (unsupported extension, Tree-sitter parse failure).
- Helper conversion functions.

Tests that actually parse ASTs are skipped when Tree-sitter is not installed.
"""

import pytest

from adduce.parsers.base import ParsedApiEndpoint, ParsedMethodCall
from adduce.parsers.tree_sitter.adapter import (
    TreeSitterSourceParser,
    _convert_method_call,
    _convert_symbol,
    _extract_api_endpoints,
    _extract_imports,
    _find_handler_below,
    _find_next_symbol,
    _framework_for_language,
    _is_code_symbol,
    _join_paths,
    _parse_endpoint_annotation,
    _parse_request_mapping_path,
)
from adduce.parsers.tree_sitter.core.models import LanguageType, SymbolInfo
from adduce.parsers.tree_sitter.core.parser import TREE_SITTER_AVAILABLE


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _symbol(
    name: str,
    symbol_type: str,
    line: int,
    parent_class: str | None = None,
    signature: str | None = None,
) -> SymbolInfo:
    return SymbolInfo(
        name=name,
        symbol_type=symbol_type,
        file_path="test.py",
        line_number=line,
        column=0,
        end_line=line,
        end_column=10,
        parent_class=parent_class,
        signature=signature,
    )


def _method_call(
    context: str,
    caller: str = "main",
    callee: str = "route",
    line: int = 1,
) -> ParsedMethodCall:
    return ParsedMethodCall(
        caller_name=caller,
        callee_name=callee,
        file_path="test.py",
        line=line,
        context=context,
    )


# ---------------------------------------------------------------------------
# TreeSitterSourceParser integration tests (require Tree-sitter)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not TREE_SITTER_AVAILABLE, reason="Tree-sitter not installed")
class TestTreeSitterSourceParserIntegration:
    @pytest.fixture
    def parser(self):
        return TreeSitterSourceParser()

    # ---- Language parsing ----------------------------------------------

    def test_parse_java(self, parser):
        code = """
package com.example.demo;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/users")
public class UserController {
    @GetMapping("/{id}")
    public User getUser(@PathVariable Long id) {
        return fetchUser(id);
    }
    private User fetchUser(Long id) {
        return new User(id, "Alice");
    }
}
"""
        result = parser.parse("UserController.java", code)
        assert not result.errors
        names = {e.name for e in result.entities}
        assert "UserController" in names
        assert "getUser" in names
        assert any(
            ep.method == "GET" and "/api/users/{id}" in ep.path
            for ep in result.api_endpoints
        )
        assert any(c.callee_name == "fetchUser" for c in result.method_calls)
        assert any("org.springframework.web.bind.annotation" in imp.module for imp in result.imports)

    def test_parse_kotlin(self, parser):
        code = """
package com.example
import org.springframework.web.bind.annotation.*

@RestController
@RequestMapping("/api/users")
class UserController {
    @GetMapping("/{id}")
    fun getUser(@PathVariable id: Long): String {
        return fetchUser(id)
    }
    private fun fetchUser(id: Long): String {
        return "user"
    }
}
"""
        result = parser.parse("UserController.kt", code)
        assert not result.errors
        names = {e.name for e in result.entities}
        assert "UserController" in names
        assert "getUser" in names
        assert any(
            ep.method == "GET" and "/api/users/{id}" in ep.path
            for ep in result.api_endpoints
        )
        assert any(c.callee_name == "fetchUser" for c in result.method_calls)

    def test_parse_python(self, parser):
        code = """
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return build_response()

def build_response():
    return {"status": "ok"}
"""
        result = parser.parse("handlers.py", code)
        assert not result.errors
        names = {e.name for e in result.entities}
        assert "health" in names
        assert "build_response" in names
        assert any(ep.method == "GET" and "/health" in ep.path for ep in result.api_endpoints)
        assert any(c.callee_name == "build_response" for c in result.method_calls)
        assert any(imp.module == "fastapi" for imp in result.imports)

    def test_parse_javascript(self, parser):
        code = """
import express from 'express';
const app = express();

app.get('/users/:id', (req, res) => {
  res.send(getUser(req.params.id));
});

function getUser(id) {
  return { id };
}
"""
        result = parser.parse("routes.js", code)
        assert not result.errors
        assert any(ep.method == "GET" and "/users/:id" in ep.path for ep in result.api_endpoints)
        assert any(c.callee_name == "getUser" for c in result.method_calls)

    def test_parse_typescript(self, parser):
        code = """
import express from 'express';
const app = express();

app.get('/users/:id', (req, res) => {
  res.send(getUser(req.params.id));
});

function getUser(id: string) {
  return { id };
}
"""
        result = parser.parse("routes.ts", code)
        assert not result.errors
        assert any(ep.method == "GET" and "/users/:id" in ep.path for ep in result.api_endpoints)
        assert any(c.callee_name == "getUser" for c in result.method_calls)

    def test_parse_go_stdlib(self, parser):
        code = """
package main
import "net/http"

func main() {
    http.HandleFunc("/api/users/{id}", getUser)
}

func getUser(w http.ResponseWriter, r *http.Request) {
    fetchUser()
    w.Write([]byte("ok"))
}

func fetchUser() {}
"""
        result = parser.parse("main.go", code)
        assert not result.errors
        names = {e.name for e in result.entities}
        assert "getUser" in names
        assert "fetchUser" in names
        assert any(
            ep.method == "GET" and "/api/users/{id}" in ep.path
            for ep in result.api_endpoints
        )
        assert any(c.callee_name == "fetchUser" for c in result.method_calls)

    def test_parse_go_gin(self, parser):
        code = """
package main
import "github.com/gin-gonic/gin"

func main() {
    r := gin.Default()
    r.GET("/api/users/:id", getUser)
}

func getUser(c *gin.Context) {}
"""
        result = parser.parse("main.go", code)
        assert not result.errors
        assert any(
            ep.method == "GET" and "/api/users/:id" in ep.path
            for ep in result.api_endpoints
        )

    def test_parse_rust_actix(self, parser):
        code = """
use actix_web::{get, web, App, HttpResponse};

#[get("/api/users/{id}")]
async fn get_user(path: web::Path<u64>) -> HttpResponse {
    let msg = build_response();
    HttpResponse::Ok().body(msg)
}

fn build_response() -> &'static str {
    "ok"
}

fn main() {
    App::new().service(get_user);
}
"""
        result = parser.parse("main.rs", code)
        assert not result.errors
        names = {e.name for e in result.entities}
        assert "get_user" in names
        assert "build_response" in names
        assert any(
            ep.method == "GET" and "/api/users/{id}" in ep.path
            for ep in result.api_endpoints
        )
        assert any(c.callee_name == "build_response" for c in result.method_calls)

    def test_parse_rust_axum(self, parser):
        code = """
use axum::{routing, Router};

async fn get_user() -> &'static str {
    "ok"
}

fn main() {
    let app = Router::new().route("/api/users/:id", routing::get(get_user));
}
"""
        result = parser.parse("main.rs", code)
        assert not result.errors
        assert any(
            ep.method == "GET" and "/api/users/:id" in ep.path
            for ep in result.api_endpoints
        )


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestTreeSitterAdapterErrors:
    def test_unsupported_extension_returns_error(self):
        parser = TreeSitterSourceParser()
        result = parser.parse("readme.txt", "hello world")
        assert result.errors
        assert "Unsupported file extension" in result.errors[0]

    def test_no_entities_for_unsupported_extension(self):
        parser = TreeSitterSourceParser()
        result = parser.parse("config.txt", "hello world")
        assert result.errors
        assert not result.entities
        assert not result.api_endpoints

    @pytest.mark.skipif(TREE_SITTER_AVAILABLE, reason="Only valid when Tree-sitter is missing")
    def test_parse_failure_when_tree_sitter_unavailable(self):
        parser = TreeSitterSourceParser()
        result = parser.parse("hello.py", "def hello(): pass")
        assert result.errors
        assert "Tree-Sitter not available" in result.errors[0]

    def test_parse_failure_propagates(self, monkeypatch):
        parser = TreeSitterSourceParser()

        def _failing_parse(*args, **kwargs):
            from adduce.parsers.tree_sitter.core.models import ParsingResult
            return ParsingResult(
                file_path=args[1] if len(args) > 1 else kwargs.get("file_path", ""),
                language=args[2] if len(args) > 2 else kwargs.get("language"),
                success=False,
                error_message="forced parse failure",
            )

        monkeypatch.setattr(parser._parser, "parse_content", _failing_parse)
        result = parser.parse("hello.py", "def hello(): pass")
        assert result.errors == ["forced parse failure"]

    def test_supported_extensions_property(self):
        parser = TreeSitterSourceParser()
        exts = parser.supported_extensions
        assert ".py" in exts
        assert ".java" in exts
        assert ".kt" in exts
        assert ".js" in exts
        assert ".ts" in exts
        assert ".go" in exts
        assert ".rs" in exts
        assert ".txt" not in exts


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


class TestImportExtraction:
    """Tests for _extract_imports regex-based import parsing."""

    def test_java_imports(self):
        code = """
import org.springframework.web.bind.annotation.*;
import java.util.List;
import static org.junit.Assert.assertEquals;
"""
        imports = _extract_imports("Test.java", code, LanguageType.JAVA)
        modules = {imp.module for imp in imports}
        # Wildcard imports are captured up to (and including) the trailing dot.
        assert "org.springframework.web.bind.annotation." in modules
        assert "java.util.List" in modules
        # Static imports are not specially handled; the keyword "static" is captured.
        assert "static" in modules

    def test_kotlin_imports(self):
        code = "import org.springframework.web.bind.annotation.*\nimport kotlin.collections.List"
        imports = _extract_imports("Test.kt", code, LanguageType.KOTLIN)
        modules = {imp.module for imp in imports}
        assert "org.springframework.web.bind.annotation." in modules
        assert "kotlin.collections.List" in modules

    def test_python_imports(self):
        code = """
import os, sys
import numpy as np
from typing import List, Dict
from fastapi import FastAPI
from module import *
"""
        imports = _extract_imports("test.py", code, LanguageType.PYTHON)
        modules = {imp.module for imp in imports}
        assert "os" in modules
        assert "sys" in modules
        assert "numpy" in modules
        assert "typing" in modules
        assert "fastapi" in modules
        assert "module" in modules
        wildcard = [imp for imp in imports if imp.module == "module"]
        assert wildcard and wildcard[0].is_wildcard

    def test_javascript_imports(self):
        code = """
import express from 'express';
import { Router } from "express";
import * as fs from 'fs';
const path = require('path');
"""
        imports = _extract_imports("test.js", code, LanguageType.JAVASCRIPT)
        modules = {imp.module for imp in imports}
        assert "express" in modules
        assert "fs" in modules
        assert "path" in modules

    def test_typescript_imports(self):
        code = 'import { Request, Response } from "express";'
        imports = _extract_imports("test.ts", code, LanguageType.TYPESCRIPT)
        assert any(imp.module == "express" for imp in imports)

    def test_go_import_block(self):
        code = """
import (
    "fmt"
    "net/http"
    "github.com/gin-gonic/gin"
)
"""
        imports = _extract_imports("main.go", code, LanguageType.GO)
        modules = {imp.module for imp in imports}
        assert "fmt" in modules
        assert "net/http" in modules
        assert "github.com/gin-gonic/gin" in modules

    def test_go_single_import(self):
        code = 'import "fmt"\nimport "os"'
        imports = _extract_imports("main.go", code, LanguageType.GO)
        modules = {imp.module for imp in imports}
        assert "fmt" in modules
        assert "os" in modules


# ---------------------------------------------------------------------------
# Endpoint extraction branches
# ---------------------------------------------------------------------------


class TestEndpointExtraction:
    """Tests for _extract_api_endpoints covering every framework branch."""

    def test_spring_annotation_endpoint(self):
        symbols = [
            _symbol("UserController", "class", 1),
            _symbol("GetMapping", "annotation", 2, signature='@GetMapping("/{id}")'),
            _symbol("getUser", "method", 3, parent_class="UserController"),
        ]
        endpoints = _extract_api_endpoints(symbols, [], LanguageType.JAVA)
        assert len(endpoints) == 1
        assert endpoints[0].method == "GET"
        assert endpoints[0].path == "/{id}"
        assert endpoints[0].handler_name == "getUser"
        assert endpoints[0].framework == "spring"

    def test_spring_class_level_base_path(self):
        symbols = [
            _symbol("RequestMapping", "annotation", 1, signature='@RequestMapping("/api/users")'),
            _symbol("UserController", "class", 2),
            _symbol("GetMapping", "annotation", 3, signature='@GetMapping("/{id}")'),
            _symbol("getUser", "method", 4, parent_class="UserController"),
        ]
        endpoints = _extract_api_endpoints(symbols, [], LanguageType.JAVA)
        assert len(endpoints) == 1
        assert endpoints[0].path == "/api/users/{id}"

    def test_kotlin_spring_endpoint(self):
        symbols = [
            _symbol("UserController", "class", 1),
            _symbol("GetMapping", "annotation", 2, signature='@GetMapping("/{id}")'),
            _symbol("getUser", "method", 3, parent_class="UserController"),
        ]
        endpoints = _extract_api_endpoints(symbols, [], LanguageType.KOTLIN)
        assert endpoints[0].framework == "spring"

    def test_fastapi_decorator_endpoint(self):
        symbols = [
            _symbol("app.get", "annotation", 1, signature='@app.get("/users")'),
            _symbol("list_users", "function", 2),
        ]
        endpoints = _extract_api_endpoints(symbols, [], LanguageType.PYTHON)
        assert len(endpoints) == 1
        assert endpoints[0].method == "GET"
        assert endpoints[0].path == "/users"
        assert endpoints[0].framework == "fastapi"

    def test_fastapi_route_call(self):
        calls = [_method_call("app.get('/users', list_users)")]
        endpoints = _extract_api_endpoints([], calls, LanguageType.PYTHON)
        assert len(endpoints) == 1
        assert endpoints[0].method == "GET"
        assert endpoints[0].path == "/users"

    def test_flask_route_default_get(self):
        calls = [_method_call("@app.route('/items')")]
        endpoints = _extract_api_endpoints([], calls, LanguageType.PYTHON)
        assert len(endpoints) == 1
        assert endpoints[0].method == "GET"
        assert endpoints[0].path == "/items"

    def test_flask_route_post(self):
        calls = [_method_call("@app.route('/items', methods=['POST'])")]
        endpoints = _extract_api_endpoints([], calls, LanguageType.PYTHON)
        assert len(endpoints) == 1
        assert endpoints[0].method == "POST"

    def test_express_route_call(self):
        calls = [_method_call("app.get('/users/:id', handler)")]
        endpoints = _extract_api_endpoints([], calls, LanguageType.JAVASCRIPT)
        assert len(endpoints) == 1
        assert endpoints[0].method == "GET"
        assert endpoints[0].path == "/users/:id"
        assert endpoints[0].framework == "express"

    def test_typescript_express_route_call(self):
        calls = [_method_call("router.post('/orders', createOrder)")]
        endpoints = _extract_api_endpoints([], calls, LanguageType.TYPESCRIPT)
        assert len(endpoints) == 1
        assert endpoints[0].method == "POST"
        assert endpoints[0].path == "/orders"

    def test_gin_route_call(self):
        calls = [_method_call("r.GET(\"/api/users\", getUser)")]
        endpoints = _extract_api_endpoints([], calls, LanguageType.GO)
        assert len(endpoints) == 1
        assert endpoints[0].method == "GET"
        assert endpoints[0].path == "/api/users"
        assert endpoints[0].framework == "gin"

    def test_gin_post_route_call(self):
        calls = [_method_call("r.POST(\"/orders\", createOrder)")]
        endpoints = _extract_api_endpoints([], calls, LanguageType.GO)
        assert len(endpoints) == 1
        assert endpoints[0].method == "POST"

    def test_go_stdlib_handlefunc(self):
        calls = [_method_call("http.HandleFunc(\"/api/users\", getUser)")]
        endpoints = _extract_api_endpoints([], calls, LanguageType.GO)
        assert len(endpoints) == 1
        assert endpoints[0].method == "GET"
        assert endpoints[0].path == "/api/users"

    def test_rust_actix_annotation(self):
        symbols = [
            _symbol("get", "annotation", 1, signature='#[get("/api/users/{id}")]'),
            _symbol("get_user", "function", 2),
        ]
        endpoints = _extract_api_endpoints(symbols, [], LanguageType.RUST)
        assert len(endpoints) == 1
        assert endpoints[0].method == "GET"
        assert endpoints[0].path == "/api/users/{id}"
        assert endpoints[0].framework == "actix"

    def test_rust_axum_route_call(self):
        calls = [_method_call(".route(\"/api/users\", routing::get(get_user))")]
        endpoints = _extract_api_endpoints([], calls, LanguageType.RUST)
        assert len(endpoints) == 1
        assert endpoints[0].method == "GET"
        assert endpoints[0].path == "/api/users"

    def test_axum_shorthand_route_call(self):
        calls = [_method_call(".route(\"/api/users/:id\", get(get_user))")]
        endpoints = _extract_api_endpoints([], calls, LanguageType.RUST)
        assert len(endpoints) == 1
        assert endpoints[0].method == "GET"
        assert endpoints[0].path == "/api/users/:id"

    def test_unrecognized_annotation_ignored(self):
        symbols = [
            _symbol("SomeAnnotation", "annotation", 1, signature='@SomeAnnotation("value")'),
            _symbol("foo", "method", 2),
        ]
        endpoints = _extract_api_endpoints(symbols, [], LanguageType.JAVA)
        assert not endpoints

    def test_annotation_without_handler_ignored(self):
        symbols = [
            _symbol("GetMapping", "annotation", 1, signature='@GetMapping("/orphan")'),
        ]
        endpoints = _extract_api_endpoints(symbols, [], LanguageType.JAVA)
        assert not endpoints


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_is_code_symbol(self):
        assert _is_code_symbol(_symbol("A", "class", 1))
        assert _is_code_symbol(_symbol("A", "method", 1))
        assert _is_code_symbol(_symbol("A", "function", 1))
        assert _is_code_symbol(_symbol("A", "procedure", 1))
        assert _is_code_symbol(_symbol("A", "object", 1))
        assert not _is_code_symbol(_symbol("A", "annotation", 1))
        assert not _is_code_symbol(_symbol("A", "variable", 1))

    def test_convert_symbol(self):
        symbol = _symbol("foo", "procedure", 5, parent_class="Bar")
        symbol.return_type = "int"
        entity = _convert_symbol(symbol)
        assert entity.name == "foo"
        assert entity.type == "method"
        assert entity.metadata["parent_class"] == "Bar"
        assert entity.metadata["return_type"] == "int"
        assert entity.is_public

    def test_convert_method_call(self):
        from adduce.parsers.tree_sitter.core.models import MethodCall
        call = MethodCall(
            caller_method="main",
            called_method="helper",
            file_path="test.py",
            line_number=10,
            call_type="direct",
            context="helper()",
        )
        parsed = _convert_method_call(call)
        assert parsed.caller_name == "main"
        assert parsed.callee_name == "helper"
        assert parsed.line == 10
        assert parsed.confidence == "high"

    def test_join_paths(self):
        assert _join_paths("", "/users") == "/users"
        assert _join_paths("/api", "") == "/api"
        assert _join_paths("/api/", "/users") == "/api/users"
        assert _join_paths("/api", "users") == "/api/users"
        assert _join_paths("/api//", "//users") == "/api/users"

    def test_parse_request_mapping_path(self):
        assert _parse_request_mapping_path('@RequestMapping("/api")') == "/api"
        assert _parse_request_mapping_path('@RequestMapping(value = "/api/v1")') == "/api/v1"
        assert _parse_request_mapping_path('@GetMapping("/users")') is None

    def test_parse_endpoint_annotation_request_method(self):
        text = '@RequestMapping(value = "/items", method = RequestMethod.POST)'
        endpoint = _parse_endpoint_annotation(text, LanguageType.JAVA)
        assert endpoint == {"method": "POST", "path": "/items",
                            "path_declared": True}

    def test_bare_annotation_has_no_declared_path(self):
        # `@PostMapping` on a class already mapped to /owners is the idiomatic
        # way to write `POST /owners`; path_declared=False tells the caller the
        # path must come from the class-level mapping or the endpoint is dropped.
        for text in ("@PostMapping", "PostMapping"):
            assert _parse_endpoint_annotation(text, LanguageType.JAVA) == {
                "method": "POST", "path": "", "path_declared": False}

    def test_bare_annotation_recognised_for_each_verb(self):
        for annotation, method in (("GetMapping", "GET"), ("PutMapping", "PUT"),
                                   ("DeleteMapping", "DELETE"),
                                   ("PatchMapping", "PATCH")):
            parsed = _parse_endpoint_annotation(annotation, LanguageType.JAVA)
            assert parsed["method"] == method
            assert parsed["path_declared"] is False

    def test_path_attribute_form(self):
        parsed = _parse_endpoint_annotation(
            '@GetMapping(path = "/x")', LanguageType.JAVA)
        assert parsed["path"] == "/x" and parsed["path_declared"] is True

    def test_find_handler_below(self):
        symbols = [
            _symbol("A", "annotation", 1),
            _symbol("foo", "method", 3),
        ]
        handler = _find_handler_below(symbols, 1)
        assert handler is not None
        assert handler.name == "foo"

    def test_find_next_symbol(self):
        symbols = [
            _symbol("ann", "annotation", 1),
            _symbol("Controller", "class", 3),
        ]
        nxt = _find_next_symbol(symbols, 1)
        assert nxt is not None
        assert nxt.name == "Controller"

    def test_framework_for_language(self):
        assert _framework_for_language(LanguageType.JAVA) == "spring"
        assert _framework_for_language(LanguageType.KOTLIN) == "spring"
        assert _framework_for_language(LanguageType.PYTHON) == "fastapi"
        assert _framework_for_language(LanguageType.JAVASCRIPT) == "express"
        assert _framework_for_language(LanguageType.TYPESCRIPT) == "express"
        assert _framework_for_language(LanguageType.GO) == "gin"
        assert _framework_for_language(LanguageType.RUST) == "actix"


class TestGoRouteCallGates:
    """The gin branch fabricated endpoints from any `.Get("string")`:
    `w.Header.Get("Content-Type")`, `field.Tag.Get("protobuf")` and
    `url.Values.Get("key")` all became GET contracts on the reference
    corpus. Same two gates the Python branch documents: a leading slash,
    and the trailing comma that means a handler argument follows."""

    def _endpoints(self, context):
        from adduce.parsers.base import ParsedMethodCall
        from adduce.parsers.tree_sitter.adapter import _extract_route_calls
        call = ParsedMethodCall(caller_name="f", callee_name="Get",
                                line=7, context=context)
        return _extract_route_calls([call], LanguageType.GO)

    def test_a_real_route_registration_is_extracted(self):
        [e] = self._endpoints('r.GET("/owners/:id", getOwner)')
        assert (e.method, e.path) == ("GET", "/owners/:id")

    def test_a_header_read_is_not_an_endpoint(self):
        assert self._endpoints('w.Header.Get("Content-Type")') == []

    def test_a_struct_tag_read_is_not_an_endpoint(self):
        assert self._endpoints('field.Tag.Get("protobuf")') == []

    def test_a_form_values_read_is_not_an_endpoint(self):
        assert self._endpoints('formValues.Get("optional_string_value")') == []

    def test_a_single_argument_client_call_is_not_an_endpoint(self):
        # resty-style: client.Get("/health") — slash-leading but no handler.
        assert self._endpoints('client.Get("/health")') == []
