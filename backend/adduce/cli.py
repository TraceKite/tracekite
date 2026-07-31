"""`adduce` on the command line: scan a repo, link an estate, print JSON.

The library surface with a face on it. Nothing here needs a server or a
database — it calls the same `scan()` and `link()` an embedding host calls, so
whatever the CLI can do, a host can do, and neither has its own copy.

    python -m adduce.cli scan  path/to/repo --repo-id myrepo
    python -m adduce.cli link  path/to/a path/to/b
    python -m adduce.cli explain path/to/a path/to/b --edge <source> <target>

Output is JSON on stdout and nothing else, so it pipes. Diagnostics go to
stderr. Every command is deterministic given `--now`, which is what lets a CI
job diff two runs.
"""

import argparse
import os
import sys

from adduce.cli_emit import emit as _emit
from adduce.cli_explain import cmd_explain
from adduce.cli_inspect import (
    cmd_coverage, cmd_deprecations, cmd_diff, cmd_drift, cmd_health,
    cmd_history, cmd_pr, cmd_resolvers, cmd_reverify, cmd_reviews,
    cmd_schema, cmd_suggest_aliases,
)


def _repo_id_for(path: str, given: str | None) -> str:
    return given or os.path.basename(os.path.abspath(path.rstrip("/")))


def _scan_all(paths, hmac_key: str):
    """Scan each path, returning (repo_id, sink) pairs in argument order."""
    from adduce import engine_config
    from adduce.services.scan import scan

    # A library caller configures the engine directly — it cannot read the
    # server's environment, and should not have to (architecture §2).
    engine_config.configure(graph_hmac_key=hmac_key)
    return [(_repo_id_for(p, None), scan(p, _repo_id_for(p, None)))
            for p in paths]


def cmd_scan(args) -> int:
    repo_id = _repo_id_for(args.path, args.repo_id)
    from adduce import engine_config
    from adduce.services.scan import scan

    engine_config.configure(graph_hmac_key=args.hmac_key)
    sink = scan(args.path, repo_id)
    from adduce.services.absence import absence_report
    from adduce.wire import ScanReport
    return _emit(ScanReport, {
        "repo_id": repo_id,
        # Stated, not implied: a consumer must be able to tell an empty
        # repository from one that could not be fully read.
        "absence": absence_report(sink).as_dict(),
        "nodes": len(sink.nodes),
        "edges": len(sink.edges),
        "claims": dict(sorted(sink.claims.items())),
        "coverage": {k: v["tier"] for k, v in sorted(sink.coverage.items())},
    })


def cmd_artifact(args) -> int:
    """Scan one repository into a content-addressed .adduce file.

    The artifact IS the publishing format: content-addressed, so CI can
    dedupe identical revisions, and self-describing, so whoever compacts
    it next month can check its wire version before trusting it. Prints
    the path on stdout and nothing else — a workflow step pipes it.
    """
    from adduce import engine_config
    from adduce.services.reingest import scan_if_changed

    engine_config.configure(graph_hmac_key=args.hmac_key)
    repo_id = _repo_id_for(args.path, args.repo_id)
    ref, reused = scan_if_changed(args.path, repo_id, args.out,
                                  head_sha=args.head_sha)
    print(ref.path)
    if reused:
        print("reused: source unchanged since the existing artifact",
              file=sys.stderr)
    return 0


def cmd_link(args) -> int:
    from adduce.db.memory_store import InMemoryLinkerStore
    from adduce.services.linker.engine import link

    scanned = _scan_all(args.paths, args.hmac_key)
    store = InMemoryLinkerStore([sink for _rid, sink in scanned])
    result = link(store.load_claims(), run_id=args.run_id, now=args.now)

    from adduce.wire import LinkReport
    return _emit(LinkReport, {
        "run_id": args.run_id,
        "repos": [rid for rid, _ in scanned],
        "claims_loaded": result.counters.get("claims_loaded", 0),
        "services": sorted(s.name for s in result.services),
        "edges": [
            {"type": e.type, "source": e.source_id, "target": e.target_id,
             "confidence": round(e.confidence, 4), "status": e.status,
             "evidence": list(e.evidence or [])}
            for e in sorted(result.edges,
                            key=lambda e: (e.type, e.source_id, e.target_id))
        ],
        # Declines are data, not silence: every counter ships with the answer.
        "counters": result.counters,
    })


def cmd_mcp(args) -> int:
    """Serve the graph to an agent over MCP stdio."""
    from adduce.mcp_server import serve

    return serve(args.artifacts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adduce",
        description="Scan repositories and link them. No server, no database.")
    parser.add_argument("--hmac-key", default=os.environ.get(
        "GRAPH_HMAC_KEY", "adduce-cli-local"),
        help="salt for redacting config values before they reach a claim")
    parser.add_argument("--config-dir", default=os.environ.get(
        "KG_CONFIG_DIR", ""),
        help="control-plane directory holding confidence.yml and the alias, "
             "roster and promotions files (default: $KG_CONFIG_DIR, else the "
             "config/ beside backend/)")
    # Logs go to stderr so stdout stays a clean JSON document: the CLI's
    # contract is that `adduce link ... | jq` works, and a log line in the
    # middle of the payload breaks every consumer at once.
    parser.add_argument("--log", default="warning",
                        choices=["debug", "info", "warning", "error"],
                        help="log level; INFO reports per-resolver timings")
    parser.add_argument("--log-format", default=None, choices=["text", "json"],
                        help="default: json when ADDUCE_LOG_FORMAT=json")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="parse one repository into claims")
    scan_p.add_argument("path")
    scan_p.add_argument("--repo-id", default=None)
    scan_p.set_defaults(func=cmd_scan)

    art_p = sub.add_parser(
        "artifact", help="scan into a content-addressed .adduce file")
    art_p.add_argument("path")
    art_p.add_argument("--out", required=True)
    art_p.add_argument("--repo-id", default=None)
    art_p.add_argument("--head-sha", default="",
                       help="commit this artifact represents; CI passes "
                            "$GITHUB_SHA so temporal queries can anchor")
    art_p.set_defaults(func=cmd_artifact)

    mcp_p = sub.add_parser(
        "mcp", help="serve the graph to an agent over MCP stdio")
    mcp_p.add_argument("artifacts", nargs="+")
    mcp_p.set_defaults(func=cmd_mcp)

    sub.add_parser("schema", help="print the published JSON Schema"
                   ).set_defaults(func=cmd_schema)

    sub.add_parser("health", help="report whether the engine is degraded"
                   ).set_defaults(func=cmd_health)

    sub.add_parser("resolvers", help="print the declared resolver order"
                   ).set_defaults(func=cmd_resolvers)

    sub.add_parser("coverage", help="per-language extraction coverage"
                   ).set_defaults(func=cmd_coverage)

    sub.add_parser("reviews", help="review decisions as labelled data"
                   ).set_defaults(func=cmd_reviews)

    diff_p = sub.add_parser("diff", help="what changed between two artifacts")
    diff_p.add_argument("before")
    diff_p.add_argument("after")
    diff_p.set_defaults(func=cmd_diff)

    # Ordered by the caller: artifacts record the commit they were scanned at
    # but not its parent, so the series order is knowledge the CLI does not
    # have. Supplied wrongly, every edge reports as flapping.
    hist_p = sub.add_parser(
        "history", help="when each edge existed, across an artifact series")
    hist_p.add_argument("artifacts", nargs="+",
                        help="artifact paths, oldest commit first")
    hist_p.add_argument("--now", default="2026-01-01T00:00:00+00:00")
    hist_p.add_argument("--consumers-of", default="",
                        help="report who depended on this node id, per commit")
    hist_p.set_defaults(func=cmd_history)

    drift_p = sub.add_parser(
        "drift", help="declared contracts vs observed, both sides cited")
    drift_p.add_argument("artifacts", nargs="+",
                         help="head artifacts (the estate as it is now)")
    drift_p.add_argument("--base", nargs="+", default=[],
                         help="base artifacts: report operations the "
                              "provider dropped that head consumers still "
                              "call")
    drift_p.set_defaults(func=cmd_drift)

    dep_p = sub.add_parser(
        "deprecations", help="deprecated contracts and their live consumers")
    dep_p.add_argument("artifacts", nargs="+")
    dep_p.add_argument("--now", default="2026-01-01T00:00:00+00:00")
    dep_p.set_defaults(func=cmd_deprecations)

    sug_p = sub.add_parser(
        "suggest-aliases",
        help="draft service_aliases.yml entries from unmatched hints; "
             "prints only, never applies")
    sug_p.add_argument("artifacts", nargs="+")
    sug_p.add_argument("--now", default="2026-01-01T00:00:00+00:00")
    sug_p.set_defaults(func=cmd_suggest_aliases)

    rev_p = sub.add_parser(
        "reverify",
        help="check citations against the current tree; downgrade rot, "
             "never delete")
    rev_p.add_argument("artifacts", nargs="+")
    rev_p.add_argument("--repo-root", required=True,
                       help="directory the evidence paths resolve against")
    rev_p.add_argument("--now", default="2026-01-01T00:00:00+00:00")
    rev_p.set_defaults(func=cmd_reverify)

    # PR mode. --changed-repo is git's knowledge, not the graph's: given
    # it, each loss says whether the provider or the consumer moved.
    pr_p = sub.add_parser(
        "pr", help="which consumers this branch breaks, with a citation")
    pr_p.add_argument("--base", nargs="+", required=True,
                      help="artifacts for the base commit")
    pr_p.add_argument("--head", nargs="+", required=True,
                      help="artifacts for the head commit")
    pr_p.add_argument("--changed-repo", action="append", default=[],
                      help="repo id this branch touched; repeatable")
    pr_p.add_argument("--comment", action="store_true",
                      help="render the pull-request comment instead of JSON")
    pr_p.add_argument("--now", default="2026-01-01T00:00:00+00:00")
    pr_p.set_defaults(func=cmd_pr)

    for name, func, helptext in (
            ("link", cmd_link, "scan repositories and join their claims"),
            ("explain", cmd_explain, "show why one edge exists")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("paths", nargs="+")
        p.add_argument("--run-id", default="linkrun_cli")
        p.add_argument("--now", default=None,
                       help="fixed timestamp; pass it to make a run "
                            "reproducible byte for byte")
        if name == "explain":
            p.add_argument("--edge", nargs=2, required=True,
                           metavar=("SOURCE", "TARGET"))
        p.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    import logging

    from adduce.run_logging import configure_logging, run_context

    from adduce import engine_config

    args = build_parser().parse_args(argv)
    configure_logging(
        json_format=None if args.log_format is None
        else args.log_format == "json",
        level=getattr(logging, args.log.upper()), stream=sys.stderr)

    # Bind the control-plane location once, before any command runs. An entry
    # point is the layer that may read the environment; core may not
    # (architecture §2), so nothing downstream will do this for us — and
    # without it `config_dir()` falls back to walking up from base.py, which
    # only lands on `config/` in a source checkout. Installed at /app/app in
    # the container it overshoots to /config, and every link-dependent
    # subcommand dies with ConfidenceTableMissing.
    engine_config.configure(config_dir=args.config_dir,
                            graph_hmac_key=args.hmac_key)
    with run_context(getattr(args, "run_id", "") or f"cli_{args.command}"):
        return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
