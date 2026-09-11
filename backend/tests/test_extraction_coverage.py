"""The coverage matrix cannot claim what the extractors cannot do.

Every language cell in `extraction_coverage.MATRIX` is pinned here with a
canonical snippet through the real code path — route cells through a real
`scan()` of a one-file repository, client cells through
`extract_http_calls`. A cell that stays green after its extractor breaks
is the exact silent gap the report exists to remove.
"""

import os

import pytest

from tracekite import engine_config
from tracekite.services.extraction_coverage import MATRIX, coverage_report
from tracekite.services.http_call_extractor import extract_http_calls

# language -> (filename, source with exactly one route on /owners)
ROUTE_SNIPPETS = {
    "java": ("src/OwnersController.java", '''
import org.springframework.web.bind.annotation.*;
@RestController
public class OwnersController {
    @GetMapping("/owners")
    public String owners() { return "ok"; }
}
'''),
    "kotlin": ("src/OwnersController.kt", '''
import org.springframework.web.bind.annotation.*
@RestController
class OwnersController {
    @GetMapping("/owners")
    fun owners(): String = "ok"
}
'''),
    "scala": ("src/OwnersController.scala", '''
import org.springframework.web.bind.annotation._
@RestController
class OwnersController {
  @GetMapping(Array("/owners"))
  def owners(): String = "ok"
}
'''),
    "javascript": ("src/app.js", '''
const express = require('express');
const app = express();
app.get('/owners', (req, res) => res.json([]));
'''),
    "typescript": ("src/app.ts", '''
import express from 'express';
const app = express();
app.get('/owners', (req, res) => res.json([]));
'''),
    "go": ("internal/routes.go", '''
package internal

import "net/http"

func Register(mux *http.ServeMux) {
\tmux.HandleFunc("GET /owners", handleOwners)
}

func handleOwners(w http.ResponseWriter, r *http.Request) {}
'''),
    "python": ("src/app.py", '''
from fastapi import FastAPI

app = FastAPI()


@app.get("/owners")
def owners():
    return []
'''),
    "rust": ("src/main.rs", '''
use axum::{routing::get, Router};

fn app() -> Router {
    Router::new().route("/owners", get(list_owners))
}
'''),
    "c#": ("src/Program.cs", '''
var app = WebApplication.Create();
var api = app.MapGroup("/api");
api.MapGet("/owners", () => "owners");
'''),
    "ruby": ("config/routes.rb", '''
Rails.application.routes.draw do
  get '/owners', to: 'owners#index'
end
'''),
    "php": ("routes/api.php", '''<?php
use Illuminate\\Support\\Facades\\Route;

Route::get('/owners', [OwnerController::class, 'index']);
'''),
}

# language -> (snippet with one outbound call, expected client tag)
CLIENT_SNIPPETS = {
    "java": ('restTemplate.getForObject("http://billing:8080/v1/x", A.class);',
             "resttemplate"),
    "kotlin": ('restTemplate.getForObject("http://billing:8080/v1/x", A::class.java)',
               "resttemplate"),
    "scala": ('restTemplate.getForObject("http://billing:8080/v1/x", classOf[A])',
              "resttemplate"),
    "javascript": ('fetch("http://billing:8080/v1/x")', "fetch"),
    "typescript": ('await fetch("http://billing:8080/v1/x")', "fetch"),
    "go": ('resp, err := http.Get("http://billing:8080/v1/x")', "net/http"),
    "python": ('requests.get("http://billing:8080/v1/x")', "requests"),
    "rust": ('let body = reqwest::get("http://billing:8080/v1/x").await?;',
             "reqwest"),
    "c#": ('await client.GetAsync("http://billing:8080/v1/x");',
           "httpclient"),
    "ruby": ("Net::HTTP.get(URI('http://billing:8080/v1/x'))", "net_http"),
    "php": ("$client->get('http://billing:8080/v1/x');", "guzzle"),
}


def routed_languages():
    return sorted(l for l, e in MATRIX.items()
                  if isinstance(e["routes"], list))


def clienty_languages():
    return sorted(l for l, e in MATRIX.items()
                  if isinstance(e["clients"], list))


class TestEveryCellIsPinned:
    def test_no_capability_cell_lacks_a_snippet(self):
        """The guard on the guard: a language added to the matrix without a
        snippet here would be a claim nothing verifies."""
        assert set(routed_languages()) == set(ROUTE_SNIPPETS)
        assert set(clienty_languages()) == set(CLIENT_SNIPPETS)


@pytest.mark.parametrize("language", routed_languages())
def test_route_extraction_through_a_real_scan(language, tmp_path):
    from tracekite.services.scan import scan

    engine_config.configure(graph_hmac_key="coverage-test")
    filename, source = ROUTE_SNIPPETS[language]
    target = tmp_path / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)

    sink = scan(str(tmp_path), f"repo_{language.replace('#', 's')}")
    endpoints = [n for n in sink.nodes if n.type == "ApiEndpoint"]
    owners = [n for n in endpoints
              if "/owners" in str(n.extra_props.get("path_template", ""))]
    assert owners, (
        f"{language}: the matrix claims route extraction, and a canonical "
        f"snippet produced no /owners endpoint — cells: "
        f"{[(n.name, n.extra_props.get('path_template')) for n in endpoints]}")


@pytest.mark.parametrize("language", clienty_languages())
def test_client_extraction_through_the_extractor(language):
    snippet, expected_client = CLIENT_SNIPPETS[language]
    sites = extract_http_calls(f"src/x.{language}", snippet, language)
    assert sites, f"{language}: the matrix claims client extraction"
    assert sites[0].client == expected_client
    assert sites[0].path_template.startswith("/v1/x")
    assert sites[0].service_hint == "billing"


class TestDeclines:
    def test_declined_languages_carry_their_reason(self):
        for language in ("c", "c++"):
            entry = MATRIX[language]
            assert entry["routes"]["declined"]
            assert entry["clients"]["declined"]

    def test_the_report_totals_match_the_matrix(self):
        report = coverage_report()
        assert report["total_languages"] == len(MATRIX)
        assert report["covered_both_sides"] == 11
        assert report["declined"] == ["c", "c++"]
