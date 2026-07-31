"""Recall: enumerate facts from the SOURCE, then ask whether the graph has them.

The opposite direction from verify_edges.py. Here ground truth is built by
reading the repo -- every compose `depends_on`, every Next.js route handler,
every MCP capability manifest -- and the graph is checked for a corresponding
edge. Anything missing is a false negative, and unlike a sampled precision
figure this is exhaustive for the categories it covers.

    python scripts/accuracy/measure_recall.py [repo_id ...]

With no argument it measures every repo in the graph.
"""
import json
import re

import yaml

from _kg import cypher_set, find, ingested_at, read_file, target_repos


def _pairs(where: str) -> set[tuple[str, str]]:
    rows = cypher_set(
        "MATCH (a:Service)-[r:CALLS_SERVICE]->(b:Service) "
        f"WHERE {where} AND 'compose_depends_on' IN r.via "
        "RETURN toLower(split(a.name,'/')[size(split(a.name,'/'))-1]) + '|' + "
        "       toLower(split(b.name,'/')[size(split(b.name,'/'))-1]);")
    return {tuple(r.split("|")) for r in rows if "|" in r}


def compose_recall(repo: str) -> tuple[int, int, list]:
    """Every `depends_on` in every compose file should be a CALLS_SERVICE edge.

    Presence is checked twice. An edge normally carries the repo that declared
    it, but when two repos declare the same dependency between the same two
    services, unification produces ONE edge attributed to whichever repo was
    linked first. Requiring this repo's id would then report a false miss --
    the fact is in the graph, just stamped with the sibling's name. So a
    repo-attributed match is preferred and a cross-repo one still counts, with
    the fallbacks reported separately rather than hidden.
    """
    expected = set()
    for path in find(repo, '-name "docker-compose*.y*ml" -o -name "compose*.y*ml"'):
        try:
            doc = yaml.safe_load(read_file(repo, path) or "") or {}
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        for name, spec in (doc.get("services") or {}).items():
            if not isinstance(spec, dict):
                continue
            dep = spec.get("depends_on")
            deps = list(dep) if isinstance(dep, (list, dict)) else ([dep] if dep else [])
            for d in deps:
                expected.add((str(name).lower(), str(d).lower()))

    own = _pairs(f"r.source_repo_id='{repo}'")
    any_repo = _pairs("true")
    missing = sorted(p for p in expected if p not in any_repo)
    elsewhere = sorted(p for p in expected if p not in own and p in any_repo)
    notes = [" -> ".join(m) for m in missing]
    notes += [f"{a} -> {b}  (present, attributed to another repo)" for a, b in elsewhere]
    return len(expected), len(missing), notes


VERB = re.compile(
    r"^export\s+(?:async\s+)?(?:function|const)\s+(GET|POST|PUT|PATCH|DELETE|HEAD)\b", re.M)


def nextjs_recall(repo: str) -> tuple[int, int, list]:
    """Next.js App Router: the directory under app/ IS the URL path."""
    expected = set()
    for path in find(repo, '-path "*/app/api/*" \\( -name "route.ts" -o -name "route.js"'
                           ' -o -name "route.tsx" \\)'):
        match = re.search(r"/app(/api/.*)/route\.[jt]sx?$", path)
        if not match:
            continue
        url = re.sub(r"/\[([^\]]+)\]", "/{}", match.group(1))
        for verb in set(VERB.findall(read_file(repo, path) or "")):
            expected.add((verb, url))

    graph = cypher_set(
        f"MATCH (e:GraphNode {{repo_id:'{repo}', type:'ApiEndpoint'}}) "
        "RETURN toUpper(coalesce(e.http_method,'')) + '|' + "
        "coalesce(e.path_template, e.name);")
    graph_pairs = {tuple(g.split("|", 1)) for g in graph if "|" in g}
    graph_paths = {p for _, p in graph_pairs}
    missing = sorted(r for r in expected
                     if r not in graph_pairs and r[1] not in graph_paths)
    return len(expected), len(missing), [f"{v} {u}" for v, u in missing]


def mcp_recall(repo: str) -> tuple[int, int, list, list]:
    """Manifest-declared tools should each be a `mcpop` provider claim.

    Ground truth is the manifest, cross-checked against a sibling tools/
    directory when one exists. Where the two disagree the manifest wins and the
    disagreement is reported separately -- a tool module with no manifest entry
    is a finding about the repo, not a graph defect.
    """
    expected, modules = set(), set()
    # Any JSON could be a manifest, so sniff by shape rather than by one
    # estate's filename convention -- same rule the parser itself uses.
    for path in find(repo, '-name "*.json" -size -256k'):
        raw = read_file(repo, path) or ""
        if '"tools"' not in raw or '"name"' not in raw:
            continue
        try:
            doc = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("tools"), list):
            continue
        server = str(doc.get("name") or "").strip()
        named = [t for t in doc["tools"]
                 if isinstance(t, dict) and str(t.get("name") or "").strip()]
        if not server or not named:
            continue
        for tool in named:
            expected.add(f"mcp:{server}/{tool['name']}")
        for mod in find(repo, f'-path "{path.rsplit("/", 1)[0]}/tools/*.py"'
                              ' -maxdepth 1 ! -name "__init__.py"'):
            modules.add(f"mcp:{server}/{mod.rsplit('/', 1)[1][:-3]}")

    graph = cypher_set(
        f"MATCH (c:ContractClaim {{repo_id:'{repo}', kind:'mcpop', "
        "direction:'provides'}) RETURN c.key;")
    missing = sorted(expected - graph)
    drift = sorted(modules ^ expected) if modules else []
    return len(expected), len(missing), missing, drift


def _find_route_lists(node) -> list:
    """Every `routes:` list in a config tree, wherever it is nested.

    Spring Cloud Gateway accepts `spring.cloud.gateway.routes` AND
    `server.webflux.routes`, and other frameworks nest theirs elsewhere again.
    Walking for the shape rather than a fixed path is what keeps this from
    being a one-framework enumerator.
    """
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "routes" and isinstance(value, list):
                found.append(value)
            else:
                found.extend(_find_route_lists(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_find_route_lists(item))
    return found


_URI_TARGET = re.compile(r"^(?:lb|https?)://([A-Za-z0-9._-]+)")


def gateway_recall(repo: str) -> tuple[int, int, list]:
    """Every declared gateway route should be a ROUTES_TO edge.

    Owed by the R7 gateway work: that resolver now depends on the route table
    being complete, so a route the parser misses silently costs call edges
    rather than announcing itself.
    """
    expected = set()
    for path in find(repo, '-name "application*.y*ml" -o -name "bootstrap*.y*ml"'):
        try:
            # Spring configs are routinely multi-document: one `---` per
            # profile. safe_load RAISES on the second document, and catching
            # that as "unparseable" silently skipped the only file in the repo
            # that declares routes -- reporting 0 of 4 as a clean 0 of 0.
            docs = list(yaml.safe_load_all(read_file(repo, path) or ""))
        except yaml.YAMLError:
            continue
        for routes in _find_route_lists(docs):
            for entry in routes:
                if not isinstance(entry, dict):
                    continue
                match = _URI_TARGET.match(str(entry.get("uri") or ""))
                if match:
                    expected.add(match.group(1).lower())

    actual = cypher_set(
        "MATCH (a)-[r:ROUTES_TO]->(b) "
        f"WHERE r.source_repo_id='{repo}' "
        "RETURN toLower(split(b.name,'/')[size(split(b.name,'/'))-1]);")
    missing = sorted(expected - actual)
    return len(expected), len(missing), missing


def report(label: str, total: int, missing: int, examples: list) -> None:
    print(f"[{label}]  declared in source: {total}"
          f"  present in graph: {total - missing}  MISSING: {missing}")
    for item in examples[:12]:
        print("   missing:", item)


for repo_id in target_repos():
    stamp = ingested_at(repo_id)
    print(f"\n=== {repo_id} ===")
    print(f"    ingested: {stamp or 'unknown'}"
          "   (a low score on a stale ingest is not a bug -- re-ingest first)")
    report("compose depends_on", *compose_recall(repo_id))
    report("next.js route handlers", *nextjs_recall(repo_id))
    report("gateway routes", *gateway_recall(repo_id))
    total_t, missing_t, examples_t, drift_t = mcp_recall(repo_id)
    report("mcp capability manifests", total_t, missing_t, examples_t)
    if drift_t:
        print(f"   note: {len(drift_t)} tool(s) differ between manifest and tools/ dir"
              " -- a repo finding, not a graph defect")
        for d in drift_t[:6]:
            print(f"     {d}")
