"""What Adduce can extract, per language — stated, not implied.

Every gap in the route/client matrices is a silently missing edge: a Ruby
service whose routes are not extracted looks exactly like a service nobody
calls. This report converts each gap into data — the same move `absence`
makes for a single scan, made once for the toolchain itself.

The matrix is DECLARED here and PINNED by test: every capability cell has a
canonical snippet in `test_extraction_coverage.py` that must extract through
the real code path, so a cell cannot stay green after its extractor breaks.
A declined cell carries its reason, because "no routes for C" is a decision
with an argument behind it, and an absent row would be indistinguishable
from a forgotten one.
"""

# language -> {"routes": [frameworks] | {"declined": why},
#              "clients": [frameworks] | {"declined": why}}
_NO_SERVER_IDIOM = (
    "no mainstream in-language HTTP routing idiom to pattern-match; "
    "services in this language declare routes via config or another "
    "language, which the config parsers already read")
_NO_CLIENT_IDIOM = (
    "HTTP clients in this language carry no dominant string-literal call "
    "idiom; matching ad-hoc socket code would guess, and a guessed call "
    "site is an invented edge")

MATRIX: dict[str, dict] = {
    "java": {"routes": ["spring"], "clients": ["resttemplate", "webclient",
                                               "okhttp", "java11", "retrofit",
                                               "feign"]},
    "kotlin": {"routes": ["spring"], "clients": ["resttemplate", "webclient",
                                                 "okhttp"]},
    "scala": {"routes": ["spring"], "clients": ["resttemplate"]},
    "javascript": {"routes": ["express", "koa", "fastify", "nestjs"],
                   "clients": ["fetch", "axios", "got", "superagent",
                               "undici", "swr", "rtk-query"]},
    "typescript": {"routes": ["express", "koa", "fastify", "nestjs"],
                   "clients": ["fetch", "axios", "got", "superagent",
                               "undici", "swr", "rtk-query"]},
    "go": {"routes": ["net/http", "echo", "gin", "fiber", "chi", "gorilla",
                      # Generated `*.pb.gw.go`: the path is a compiled
                      # pattern, not a literal, so it needs its own decoder.
                      "grpc-gateway"],
           "clients": ["net/http", "resty"]},
    "python": {"routes": ["fastapi", "flask"],
               "clients": ["requests", "httpx", "aiohttp", "urllib3"]},
    "rust": {"routes": ["actix", "rocket", "axum"], "clients": ["reqwest"]},
    "c#": {"routes": ["aspnetcore-attributes"],
           "clients": ["httpclient", "restsharp", "refit"],
           # Minimal APIs (app.MapGet) are NOT extracted: the C# tree-sitter
           # pass yields no method calls, so the adapter's MapGet branch
           # never fires. Recorded here because a gap that looks covered is
           # the exact failure this report exists to remove.
           "gaps": ["aspnetcore-minimal-apis"]},
    "ruby": {"routes": ["rails", "sinatra"],
             "clients": ["net_http", "faraday", "httparty", "restclient"]},
    "php": {"routes": ["laravel", "slim", "symfony"],
            "clients": ["guzzle", "laravel_http", "curl"]},
    "c": {"routes": {"declined": _NO_SERVER_IDIOM},
          "clients": {"declined": _NO_CLIENT_IDIOM}},
    "c++": {"routes": {"declined": _NO_SERVER_IDIOM},
            "clients": {"declined": _NO_CLIENT_IDIOM}},
}


def coverage_report() -> dict:
    """The matrix as one queryable document, gaps totalled up front.

    `covered` counts languages with at least one framework on both sides;
    a reader deciding whether to trust an estate's graph starts from that
    number, not from scrolling the table.
    """
    languages = []
    for language in sorted(MATRIX):
        entry = MATRIX[language]
        languages.append({
            "language": language,
            "routes": entry["routes"],
            "clients": entry["clients"],
        })
    both = sum(1 for e in MATRIX.values()
               if isinstance(e["routes"], list)
               and isinstance(e["clients"], list))
    return {
        "languages": languages,
        "covered_both_sides": both,
        "declined": sorted(l for l, e in MATRIX.items()
                           if not isinstance(e["routes"], list)),
        "total_languages": len(MATRIX),
    }
