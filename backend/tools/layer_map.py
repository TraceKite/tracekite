"""Layer assignments for the architecture checker.

Kept separate from the checker so the executable stays small enough to review
without hiding the import-analysis rules in a generated file.
"""

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
    # The one CLI command that talks to a server: HTTP client for ingest.
    ("ingest_client", "server"),
    ("agent_setup", "server"),
    ("cli_emit", "server"),
    ("cli_explain", "server"),
    # MCP stdio transport over the library: a surface, like cli.
    ("mcp_server", "server"),
    # MCP answer-envelope wrapper: composes classification + envelope.
    ("mcp_envelope", "server"),
    # Shared status classification for consumers_of and trace: pure.
    ("status_classify", "core"),
    # Scan metadata distillation for completeness/truncation: pure.
    ("scan_meta", "core"),
    # Public framework integration facade: composes scan/link, returns answers.
    ("facade", "server"),
    # Git metadata collection for snapshot identity: I/O, server layer.
    ("source_meta", "server"),
    ("cli_inspect", "server"),
    ("config", "server"),
    ("middleware", "server"),
    ("routes", "server"),
    ("services.ingestion_service", "server"),
    ("services.job_handlers", "server"),
    # Validates and spools uploaded git bundles for the ingest route.
    ("services.ingest_upload", "server"),
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
    # The versioned intelligence-answer contract: typed models only.
    ("answer", "core"),
    # Pure completeness evaluation over snapshot metadata.
    ("completeness", "core"),
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
