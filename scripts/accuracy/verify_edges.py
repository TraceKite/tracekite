"""Precision: independently verify graph edges against the source they cite.

Nothing here asks the graph whether it agrees with itself. Each edge names a
file and line as evidence; this reads that line out of the ingested clone and
decides whether the claim actually holds there. TP means the source supports
the edge, FP? means it does not, and UNVERIFIABLE means the check could not be
made mechanically and needs a human read.

    python scripts/accuracy/verify_edges.py [repo_id ...] [--json]

With no repo argument it verifies every repo in the graph.
"""
import json
import os
import re
import sys
from collections import Counter

from _kg import cypher, evidence_parts, near, read_file, target_repos

ROUTE_MARKERS = re.compile(
    r"@(?:app|router|api|blueprint|bp)\.(get|post|put|patch|delete|route)"
    r"|@(?:Get|Post|Put|Patch|Delete|Request)Mapping"
    # HandlePath before Handle: alternation is ordered, and `Handle` would
    # otherwise win and then fail on the `\(`. grpc-gateway's
    # `s.HandlePath(http.MethodGet, ...)` is a real route registration, and
    # missing it made the checker flag a correct edge as a false positive.
    r"|\.(?:Get|Post|Put|Patch|Delete|HandleFunc|HandlePath|Handle)\s*\("
    r"|(?:app|router|r|mux)\.(?:get|post|put|patch|delete)\s*\("
    r"|(?:get|post|put|patch|delete)\s*\(\s*[\"'`/]"
    r"|@(?:app_)?route"
    # Next.js App Router: the directory IS the path and the exported
    # verb-named function or const IS the handler.
    r"|export\s+(?:async\s+)?(?:function|const)\s+(?:GET|POST|PUT|PATCH|DELETE|HEAD)\b",
    re.IGNORECASE)

results: list[dict] = []


def record(repo: str, stratum: str, row: dict, verdict: str, why: str) -> None:
    results.append({"repo": repo, "stratum": stratum, "verdict": verdict,
                    "why": why, **row})


def context_for(repo: str, row: dict, radius: int) -> tuple[str | None, str, int | None]:
    path, line = evidence_parts(row.get("ev", ""))
    text = read_file(repo, path) if path else None
    return near(text, line, radius), path or "", line


def check_exposes(repo: str) -> None:
    for row in cypher(
            "MATCH (a)-[r:EXPOSES]->(b:HttpContract) "
            f"WHERE r.source_repo_id='{repo}' AND r.via=['annotation'] "
            "RETURN r.evidence[0] AS ev, b.method AS method, b.path_template AS path "
            "ORDER BY rand() LIMIT 25;"):
        ctx, path, line = context_for(repo, row, 3)
        if ctx is None:
            record(repo, "EXPOSES/annotation", row, "UNVERIFIABLE", f"no such file: {path}")
            continue
        tail = re.sub(r"\{.*\}", "", (row.get("path") or "").strip("/").split("/")[-1])
        has_route = bool(ROUTE_MARKERS.search(ctx))
        has_path = (tail and tail in ctx) or (row.get("path") or "") in ctx
        if has_route and (has_path or not tail):
            record(repo, "EXPOSES/annotation", row, "TP",
                   "route marker + path fragment at cited line")
        elif has_route:
            record(repo, "EXPOSES/annotation", row, "TP_WEAK",
                   "route marker present, path fragment not literal")
        else:
            record(repo, "EXPOSES/annotation", row, "FP?",
                   f"no route marker near {path}:{line}")


def check_depends_on(repo: str) -> None:
    for row in cypher(
            "MATCH (a:Service)-[r:CALLS_SERVICE]->(b:Service) "
            f"WHERE r.source_repo_id='{repo}' AND 'compose_depends_on' IN r.via "
            "RETURN r.evidence[0] AS ev, a.name AS src, b.name AS dst "
            "ORDER BY rand() LIMIT 20;"):
        path, _ = evidence_parts(row.get("ev", ""))
        text = read_file(repo, path) if path else None
        if text is None:
            record(repo, "CALLS/depends_on", row, "UNVERIFIABLE", f"no such file: {path}")
            continue
        dst = (row.get("dst") or "").split("/")[-1]
        if re.search(rf"^\s*-?\s*{re.escape(dst)}\s*:?\s*$", text, re.M) or f" {dst}" in text:
            record(repo, "CALLS/depends_on", row, "TP",
                   f"'{dst}' declared in {os.path.basename(path)}")
        else:
            record(repo, "CALLS/depends_on", row, "FP?", f"'{dst}' not found in {path}")


def check_env_host(repo: str) -> None:
    for row in cypher(
            "MATCH (a:Service)-[r:CALLS_SERVICE]->(b:Service) "
            f"WHERE r.source_repo_id='{repo}' AND 'compose_env_host' IN r.via "
            "RETURN r.evidence[0] AS ev, a.name AS src, b.name AS dst LIMIT 15;"):
        path, _ = evidence_parts(row.get("ev", ""))
        text = read_file(repo, path) if path else None
        if text is None:
            record(repo, "CALLS/env_host", row, "UNVERIFIABLE", f"no such file: {path}")
            continue
        dst = (row.get("dst") or "").split("/")[-1]
        if re.search(rf"https?://{re.escape(dst)}[:/\s]", text):
            record(repo, "CALLS/env_host", row, "TP", f"env URL points at http://{dst}")
        elif dst in text:
            record(repo, "CALLS/env_host", row, "TP_WEAK",
                   f"'{dst}' present but not as a URL host")
        else:
            record(repo, "CALLS/env_host", row, "FP?", f"'{dst}' not in {path}")


def check_invokes(repo: str) -> None:
    """Direct call edges: the contract path must be literal at the call site."""
    for row in cypher(
            "MATCH (a)-[r:INVOKES]->(b:HttpContract) "
            f"WHERE r.source_repo_id='{repo}' AND NOT 'gateway_rewrite' IN r.via "
            "RETURN r.evidence[0] AS ev, b.method AS method, b.path_template AS path;"):
        ctx, path, line = context_for(repo, row, 2)
        if ctx is None:
            record(repo, "INVOKES/config_host", row, "UNVERIFIABLE", f"no such file: {path}")
            continue
        literal = re.sub(r"\{\}", "", row.get("path") or "").rstrip("/")
        if literal and literal in ctx:
            record(repo, "INVOKES/config_host", row, "TP",
                   f"path '{literal}' literal at cited line")
        else:
            record(repo, "INVOKES/config_host", row, "FP?",
                   f"path '{row.get('path')}' not at {path}:{line}")


def check_invokes_gateway(repo: str) -> None:
    """Gateway-rewritten call edges — both halves of the reasoning checked.

    Substring-matching the contract path at the call site is NOT a real check
    here: the rewritten `/vets` is trivially a substring of the public
    `/api/vet/vets`, so a broken rewrite would still pass. What actually needs
    verifying is the second evidence entry -- the gateway route line that
    justified rewriting the path at all. If that line does not name the target
    service, the edge rests on nothing.
    """
    for row in cypher(
            "MATCH (a)-[r:INVOKES]->(b:HttpContract) "
            f"WHERE r.source_repo_id='{repo}' AND 'gateway_rewrite' IN r.via "
            "RETURN r.evidence[0] AS ev, r.evidence[1] AS route_ev, "
            "b.path_template AS path, b.service_scope AS target, "
            "r.route_repo AS route_repo;"):
        route_ev = row.get("route_ev") or ""
        if not route_ev:
            record(repo, "INVOKES/gateway", row, "FP?",
                   "gateway edge cites no route evidence")
            continue
        rpath, rline = evidence_parts(route_ev)
        # A gateway shared by two repos routes from whichever repo declared it,
        # so the route's evidence path only resolves against `route_repo`.
        # Reading it from the consumer's repo reported "no such file" on every
        # cross-repo edge and left a third of this stratum unverified.
        route_repo = row.get("route_repo") or repo
        rtext = read_file(route_repo, rpath) if rpath else None
        rctx = near(rtext, rline, 4)
        if rctx is None:
            record(repo, "INVOKES/gateway", row, "UNVERIFIABLE",
                   f"no such route file: {rpath}")
            continue
        target = (row.get("target") or "").split("/")[-1]
        if target and target in rctx:
            record(repo, "INVOKES/gateway", row, "TP",
                   f"route at {rpath}:{rline} names '{target}'")
        else:
            record(repo, "INVOKES/gateway", row, "FP?",
                   f"route at {rpath}:{rline} does not name '{target}'")


def check_mcp(repo: str) -> None:
    """An mcpop contract must be named by the manifest its evidence cites."""
    for row in cypher(
            "MATCH (a)-[r:EXPOSES]->(b:ContractOperation) "
            f"WHERE r.source_repo_id='{repo}' AND 'mcp_registration' IN r.via "
            # ContractOperation carries the tool in `rpc`; it has no `name`.
            # Reading b.name returned NULL for every row and scored the whole
            # stratum 0.00 -- the checker was broken, not the graph.
            "RETURN r.evidence[0] AS ev, coalesce(b.rpc, b.key, b.id) AS tool "
            "ORDER BY rand() LIMIT 25;"):
        path, _ = evidence_parts(row.get("ev", ""))
        text = read_file(repo, path) if path else None
        if text is None:
            record(repo, "EXPOSES/mcp", row, "UNVERIFIABLE", f"no such file: {path}")
            continue
        tool = (row.get("tool") or "").split("/")[-1]
        if tool and f'"{tool}"' in text:
            record(repo, "EXPOSES/mcp", row, "TP", f"tool '{tool}' declared in {path}")
        else:
            record(repo, "EXPOSES/mcp", row, "FP?", f"tool '{tool}' not in {path}")


def check_sql(repo: str) -> None:
    for row in cypher(
            "MATCH (a)-[r:READS_FROM|WRITES_TO]->(b) "
            f"WHERE r.source_repo_id='{repo}' AND 'sql' IN r.via "
            "RETURN r.evidence[0] AS ev, type(r) AS edge, coalesce(b.name,b.id) AS ds "
            "ORDER BY rand() LIMIT 15;"):
        ctx, path, line = context_for(repo, row, 4)
        if ctx is None:
            record(repo, "READS/WRITES sql", row, "UNVERIFIABLE", f"no such file: {path}")
            continue
        table = (row.get("ds") or "").split(":")[-1]
        if table and re.search(re.escape(table), ctx, re.IGNORECASE):
            record(repo, "READS/WRITES sql", row, "TP", f"table '{table}' at cited line")
        else:
            record(repo, "READS/WRITES sql", row, "FP?",
                   f"table '{table}' not at {path}:{line}")


CHECKS = (check_exposes, check_depends_on, check_env_host, check_invokes_gateway,
          check_invokes, check_mcp, check_sql)

for repo_id in target_repos():
    for check in CHECKS:
        check(repo_id)

if "--json" in sys.argv:
    print(json.dumps(results, indent=1))
else:
    by_stratum: dict[str, Counter] = {}
    for r in results:
        by_stratum.setdefault(r["stratum"], Counter())[r["verdict"]] += 1
    print(f"{'stratum':<26} {'TP':>4} {'WEAK':>5} {'FP?':>4} {'UNVERIF':>8}  precision")
    for stratum, counts in sorted(by_stratum.items()):
        tp, weak, fp = counts["TP"], counts["TP_WEAK"], counts["FP?"]
        judged = tp + weak + fp
        rate = f"{(tp + weak) / judged:.2f}" if judged else "-"
        print(f"{stratum:<26} {tp:>4} {weak:>5} {fp:>4} {counts['UNVERIFIABLE']:>8}  {rate:>9}")
    for r in results:
        if r["verdict"] == "FP?":
            print(f"  FP? [{r['stratum']}] {r['why']}")
