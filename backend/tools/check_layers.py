"""Enforce the layering rule: arrows point down only (architecture §2).

    server   may import anything
    store    may import core
    parsers  may import core
    core     imports nothing above it

`parsers` and `store` are siblings: neither may import the other, or the
engine cannot parse without a database and A9 becomes unreachable.

**This parses imports; it does not search text.** The doc's original violation
table was produced by grepping for "neo4j" and "fastapi" and counted two
string literals as imports — in a codebase whose whole job is to read other
people's framework names, a text search cannot tell a dependency from a
detection rule. See architecture §2.

Run:  python backend/tools/check_layers.py [--list]
Exit: 0 clean, 1 violations found.
"""

import argparse
import ast
import pathlib
import sys

APP = pathlib.Path(__file__).resolve().parent.parent / "adduce"
# Bottom-up. Equal rank means sibling: siblings may not import each other.
RANK = {"core": 0, "parsers": 1, "store": 1, "server": 2}
# First match wins, so longer prefixes are listed before the packages that
# contain them. A module absent from this table is an error, not a default:
# silently ranking new code as `server` would let it import anything.
LAYERS: tuple[tuple[str, str], ...] = (
    # --- store: the only layer permitted to perform I/O -------------------
    ("db.store_config", "store"),
    ("db", "store"),
    ("services.graph_reader", "store"),
    ("services.graph_writer", "store"),
    ("services.link_writer", "store"),
    ("services.linker_store", "store"),
    # --- server: composition, transport, scheduling -----------------------
    ("main", "server"),
    # Composes scan + link + a store; imports downward only.
    ("cli", "server"),
    ("agent_setup", "server"),
    ("cli_emit", "server"),
    ("cli_explain", "server"),
    # MCP stdio transport over the library: a surface, like cli.
    ("mcp_server", "server"),
    ("cli_inspect", "server"),
    ("config", "server"),
    ("middleware", "server"),
    ("routes", "server"),
    ("services.ingestion_service", "server"),
    ("services.job_handlers", "server"),
    # Spans parsers and store to decide whether to scan at all.
    ("services.reingest", "server"),
    # Drives scan (parsers) into artifacts (store): orchestration.
    ("services.parallel_map", "server"),
    # Pool orchestration over the parsers' pure pieces: server, like the
    # per-repo pool it extends.
    ("services.sharded_scan", "server"),
    ("services.job_queue", "server"),
    ("services.calibration", "server"),
    ("services.calibration_estates", "server"),
    ("services.calibration_io", "server"),
    # Pure functions over the config shape and edges — no imports at all —
    # consumed from core (reliability) and server (calibration) alike.
    ("services.calibration_tiers", "core"),
    # Publishing a measurement is I/O and picking an exporter is a deployment
    # decision — both belong to whoever composes the app, not to the engine.
    ("metrics_export", "server"),
    ("run_logging", "server"),
    ("services.repo_service", "server"),
    # Mutates the operator control plane; core only reads it.
    ("services.control_plane", "server"),
    # --- parsers: bytes + path -> structured data / claims ----------------
    ("parsers", "parsers"),
    ("services.ingest_artifacts", "parsers"),
    ("services.ingest_claims", "parsers"),
    ("services.ingest_deps", "parsers"),
    ("services.manifest_lines", "parsers"),
    ("services.claim_sink", "parsers"),
    ("services.ingest_config_defs", "parsers"),
    ("services.ingest_source", "parsers"),
    ("services.scan", "parsers"),
    ("services.sink_merge", "parsers"),
    ("services.absence", "parsers"),
    ("services.agents_extractor", "parsers"),
    ("services.call_graph_resolver", "parsers"),
    ("services.data_extractor", "parsers"),
    ("services.env_extractor", "parsers"),
    ("services.file_classifier", "parsers"),
    ("services.file_scanner", "parsers"),
    ("services.go_route_extractor", "parsers"),
    ("services.grpc_gateway_routes", "parsers"),
    ("services.framework_routes", "parsers"),
    ("services.grpc_extractor", "parsers"),
    ("services.http_call_extractor", "parsers"),
    ("services.http_call_js", "parsers"),
    ("services.http_call_url", "parsers"),
    ("services.rb_route_extractor", "parsers"),
    ("services.php_route_extractor", "parsers"),
    ("services.csharp_route_extractor", "parsers"),
    ("services.extraction_coverage", "parsers"),
    ("services.flag_guards", "parsers"),
    ("services.scip_import", "parsers"),
    # Pure decision logic with the tree read injected — core, so a library
    # host can reverify without the server.
    ("services.evidence_reverify", "core"),
    ("services.js_route_extractor", "parsers"),
    ("services.jvm_route_extractor", "parsers"),
    ("services.messaging_extractor", "parsers"),
    # --- core: claims, resolvers, evidence, confidence --------------------
    ("engine_config", "core"),
    # Reads the control plane and asks a store if given; the store
    # arrives as an argument, so this stays above nothing.
    ("engine_health", "server"),
    # The published wire contract: values only, no engine logic.
    ("wire", "core"),
    # Value objects for what a run cost. Reads a monotonic clock and nothing
    # else — no export, no I/O; those live in `metrics_export` (server).
    ("telemetry", "core"),
    ("models", "core"),
    ("utils", "core"),
    ("services.linker", "core"),
    ("services.claims", "core"),
    ("services.redaction", "core"),
    ("services.graph_factories", "core"),
)


# A route may fetch, validate and hand off. It may not compute a fact about
# the graph: an iterative accumulation in a handler is logic the library
# surface can never reproduce, so `pip install` silently answers differently
# from `docker compose up` — the drift that kills dual-surface projects.
# Found two real cases when first switched on: node-kind/dead-end
# classification in the service map, and an ownership tie-break in the
# rollup. Both moved to core, where both surfaces call one implementation.
#
# `for` STATEMENTS only. A comprehension shaping a response row is
# formatting, and 8 of 27 handlers legitimately use one; a loop that
# accumulates is where decisions hide.
_ROUTE_DECORATORS = ("get", "post", "put", "patch", "delete")


def check_route_computation() -> list[str]:
    """Routes orchestrate; they do not compute (architecture §2)."""
    violations = []
    routes_dir = APP / "routes"
    for path in sorted(routes_dir.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(isinstance(d, ast.Call)
                       and isinstance(d.func, ast.Attribute)
                       and d.func.attr in _ROUTE_DECORATORS
                       for d in node.decorator_list):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, (ast.For, ast.AsyncFor, ast.While)):
                    violations.append(
                        f"routes/{path.name}:{inner.lineno}: handler "
                        f"{node.name!r} iterates to build its answer. That is "
                        f"computation about the graph, and a library host "
                        f"cannot reproduce it — move it into "
                        f"services/linker/ and call it from here.")
    return violations


def module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(APP).with_suffix("")
    parts = [p for p in rel.parts if p != "__init__"]
    return ".".join(parts)


def layer_of(module: str) -> str | None:
    for prefix, layer in LAYERS:
        if module == prefix or module.startswith(prefix + "."):
            return layer
    return None


def imports_of(path: pathlib.Path) -> set[str]:
    """Every `app.*` module this file imports, at any nesting depth.

    Function-level imports count: deferring an import to call time changes
    when the coupling bites, not whether it exists.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            # `from app.x import y` may name a module rather than a symbol.
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return {m[len("adduce."):] for m in found if m.startswith("adduce.")}


def resolve(target: str) -> str | None:
    """Longest known module prefix, so `services.linker.base.ClaimRecord`
    resolves to the module rather than falling through as unknown."""
    parts = target.split(".")
    while parts:
        candidate = ".".join(parts)
        if layer_of(candidate) is not None:
            return candidate
        parts.pop()
    return None


def is_package_marker(path: pathlib.Path) -> bool:
    """An empty `__init__.py` declares a package and imports nothing, so it
    cannot violate the rule and needs no layer."""
    return path.name == "__init__.py" and not path.read_text().strip()


# Core primitive modules a route may never import: reaching for one is how
# a fact about the graph ends up computed inline in a handler, where the
# library surface can never reproduce it. Routes call core ENTRY
# POINTS (engine.link, crossings.assemble_crossings, rollup_view...) —
# the computation happens below; the route only orchestrates.
_ROUTE_FORBIDDEN = (
    "services.linker.modules", "services.linker.base",
    "services.linker.edge_policy", "utils.canonical",
)


def scan() -> tuple[list[tuple], list[str]]:
    violations, unassigned = [], []
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts or is_package_marker(path):
            continue
        src = module_name(path)
        src_layer = layer_of(src)
        if src_layer is None:
            unassigned.append(src)
            continue
        for raw in sorted(imports_of(path)):
            target = resolve(raw)
            if target is None or target == src:
                continue
            dst_layer = layer_of(target)
            if dst_layer is None:
                continue
            if src.startswith("routes") and any(
                    target == f or target.startswith(f + ".")
                    for f in _ROUTE_FORBIDDEN):
                violations.append((src, src_layer, target, dst_layer,
                                   "route-computes"))
            if RANK[src_layer] < RANK[dst_layer]:
                violations.append((src, src_layer, target, dst_layer, "upward"))
            elif (RANK[src_layer] == RANK[dst_layer]
                  and src_layer != dst_layer):
                violations.append((src, src_layer, target, dst_layer, "sibling"))
    return violations, unassigned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true",
                        help="print every module and its layer")
    args = parser.parse_args()

    violations, unassigned = scan()

    if args.list:
        by_layer: dict[str, list[str]] = {}
        for path in sorted(APP.rglob("*.py")):
            if "__pycache__" in path.parts or is_package_marker(path):
                continue
            name = module_name(path)
            by_layer.setdefault(layer_of(name) or "UNASSIGNED", []).append(name)
        for layer in ["core", "parsers", "store", "server", "UNASSIGNED"]:
            names = by_layer.get(layer, [])
            print(f"\n{layer} ({len(names)})")
            for name in names:
                print(f"  {name}")
        print()

    if unassigned:
        print(f"{len(unassigned)} module(s) not assigned to a layer — add them "
              f"to LAYERS in this file:")
        for name in unassigned:
            print(f"  {name}")
        print()

    computing = check_route_computation()
    if computing:
        print(f"{len(computing)} ROUTE(S) COMPUTING:\n")
        for line in computing:
            print(f"  {line}\n")

    if violations:
        print(f"{len(violations)} LAYERING VIOLATION(S):\n")
        for src, sl, dst, dl, kind in violations:
            arrow = {"upward": "imports UP to",
                     "sibling": "imports SIBLING",
                     "route-computes": "imports core PRIMITIVE"}[kind]
            print(f"  [{sl:7}] {src}")
            print(f"            {arrow} [{dl}] {dst}")
        return 1

    if unassigned or computing:
        return 1
    print("layering holds: arrows point down only, routes do not compute")
    return 0


if __name__ == "__main__":
    sys.exit(main())
