"""Parsers never raise on garbage.

The error rule is absolute: a parser returns None or [] for input it does
not recognise — it never raises. One estate holds every kind of half-saved
file, merge-conflict marker and truncated checkout there is, and a parser
that crashes on one of them takes the whole repo's scan down with it.

Deterministic on purpose: the mutations come from a seeded generator, so a
failure here reproduces exactly and CI cannot flake. The seeds are real
fixture content — mutated truth finds parser edges that pure noise never
reaches.
"""

import random

import pytest

from adduce.parsers.parser_registry import parse_file

SEED_FILES = {
    "docker-compose.yml": (
        "services:\n  billing:\n    build: .\n    environment:\n"
        "      A: http://x:8080\n    depends_on: [orders]\n"),
    "deploy/k8s.yaml": (
        "apiVersion: apps/v1\nkind: Deployment\n"
        "metadata: {name: a, namespace: p}\nspec:\n  template:\n"
        "    spec:\n      containers: [{name: c, image: i,\n"
        "        env: [{name: X, value: 'http://y:1'}]}]\n"),
    "src/app.py": (
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        "@app.get('/owners')\ndef owners():\n"
        "    return requests.get('http://b:1/v1/x')\n"),
    "internal/routes.go": (
        'package internal\nimport "net/http"\n'
        'func R(m *http.ServeMux) { m.HandleFunc("GET /x", h) }\n'),
    "src/App.tsx": (
        "export function App() {\n"
        "  fetch(`http://b:1/v1/${id}`);\n"
        '  new WebSocket("ws://b:1/live");\n  return null;\n}\n'),
    "src/C.java": (
        "import org.springframework.web.bind.annotation.*;\n"
        "@RestController public class C {\n"
        '  @GetMapping("/x") public String x() { return ""; }\n}\n'),
    "config/routes.rb": "resources :owners, only: [:index]\n",
    "routes/api.php": "<?php\nRoute::get('/x', [C::class, 'i']);\n",
    "main.tf": 'resource "aws_sqs_queue" "q" { name = "orders" }\n',
    "api.proto": ('syntax = "proto3";\npackage a.b;\n'
                  "service S { rpc Get (Req) returns (Res); }\n"),
    "schema.graphql": "type Query { owners: [Owner] }\n",
    "cron.d/nightly": "0 3 * * * app curl http://b:1/v1/x\n",
    "deploy/app.nomad": ('job "a" { group "g" { task "t" {\n'
                         '  service { name = "a" }\n} } }\n'),
    "deploy/a.service": "[Unit]\nDescription=A\n[Service]\nExecStart=/a\n",
    "playbook.yml": ("- hosts: all\n  tasks:\n"
                     "    - docker_container:\n        name: a\n"),
    "Chart/values.yaml": "image:\n  repository: r/i\n  tag: '1'\n",
    "package.json": '{"name": "a", "dependencies": {"x": "1.0.0"}}\n',
}


def mutations(content: str, rng: random.Random) -> list[str]:
    """Deterministic damage: the ways files actually break."""
    data = content.encode()
    out = [
        "",                                  # empty file
        "\x00" * 64,                         # binary junk
        content[: len(content) // 2],        # truncated save
        content + content,                   # duplicated buffer
        "<<<<<<< HEAD\n" + content + "\n=======\nx\n>>>>>>> other\n",
        content.replace(":", "", 1),         # one structural char gone
        "﻿" + content,                  # BOM
        content.replace("\n", "\r\n"),       # CRLF
        "{" * 200,                           # nesting bomb, small
        "a: &a [*a]\n",                      # YAML self-reference
        "\udcff".join(content[:40]),         # lone surrogates
    ]
    for _ in range(6):
        damaged = bytearray(data)
        for _ in range(max(1, len(damaged) // 20)):
            damaged[rng.randrange(len(damaged) or 1) % max(
                1, len(damaged))] = rng.randrange(256)
        out.append(damaged.decode("utf-8", errors="replace"))
    return out


@pytest.mark.parametrize("path", sorted(SEED_FILES))
def test_no_parser_raises_on_damaged_input(path):
    rng = random.Random(0xADDCE)
    for damaged in mutations(SEED_FILES[path], rng):
        # A raise here is the bug; whatever else the parser returns for
        # garbage — None, [], a partial result — is its own business.
        result = parse_file(path, damaged)
        assert isinstance(result, dict)


def test_extractors_survive_the_same_damage():
    """The direct-call extractors sit outside parse_file's registry."""
    from adduce.services.http_call_extractor import (
        extract_http_calls, extract_webhook_registrations,
    )
    from adduce.services.php_route_extractor import extract_php_routes
    from adduce.services.rb_route_extractor import extract_rb_routes

    rng = random.Random(0xADDCE)
    for path, seed in sorted(SEED_FILES.items()):
        for damaged in mutations(seed, rng):
            extract_http_calls(path, damaged, "typescript")
            extract_http_calls(path, damaged, "python")
            extract_webhook_registrations(damaged)
            extract_rb_routes("config/routes.rb", damaged)
            extract_php_routes("routes/api.php", damaged)
