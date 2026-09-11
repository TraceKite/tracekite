"""The CLI's introspection commands: what the engine is, not what it does.

Split from `cli.py` at the seam that was already there. `scan`, `link` and
`explain` run the pipeline; these five answer questions *about* it — the
published schema, whether the engine is degraded, which resolvers run in what
order, what changed between two artifacts, and when each edge existed.

They share a shape the pipeline commands do not: none of them takes a
repository, and every one is safe to run against a system in any state.
"""

import json
import sys

from tracekite.cli_emit import emit


def cmd_schema(args) -> int:
    """Emit the published JSON Schema, so a consumer in another language can
    validate an artifact without running Python."""
    from tracekite.wire import json_schemas

    json.dump(json_schemas(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def cmd_history(args) -> int:
    """When each edge existed, across an ordered artifact series.

    Artifacts record the commit they were scanned at but not its parent, so
    the order is the caller's knowledge — a CI job walking git history has it
    and this does not. Supplying them out of order reports every edge as
    flapping, which is why the commits are echoed back in the report.
    """
    from tracekite.db.artifact import read_meta
    from tracekite.db.artifact_reader import read_claims
    from tracekite.services.linker.engine import link
    from tracekite.services.linker.history import edge_history
    from tracekite.wire import HistoryReport

    series, commits = [], []
    for index, path in enumerate(args.artifacts):
        commit = read_meta(path).get("head_sha") or f"artifact-{index}"
        result = link(read_claims(path), run_id=f"linkrun_history_{index}",
                      now=args.now)
        series.append((commit, result.edges))
        commits.append(commit)

    if args.consumers_of:
        from tracekite.services.linker.history import consumers_over_time
        from tracekite.wire import ConsumerHistoryReport

        report = consumers_over_time(series, args.consumers_of)
        return emit(ConsumerHistoryReport, {"commits": commits, **report})

    return emit(HistoryReport, {
        "commits": commits,
        "edges": [h.as_dict() for h in edge_history(series)],
    })


def cmd_deprecations(args) -> int:
    """Every deprecated contract, and who still calls it.

    One compaction of the given artifacts. An entry with an empty consumer
    list is the answer that permits deletion — measured, none found — which
    is why it appears rather than being omitted.
    """
    from tracekite.services.linker.deprecations import deprecation_report
    from tracekite.wire import DeprecationReport

    result = _link_artifacts(args.artifacts, "linkrun_deprecations", args.now)
    return emit(DeprecationReport, {
        "contracts": deprecation_report(result.edges, result.rendezvous)})


def cmd_suggest_aliases(args) -> int:
    """Alias suggestions mined from declines — surfaced, never applied.

    Prints draft `service_aliases.yml` entries for unmatched consumer
    hints. Nothing is written anywhere: an alias is an operator assertion
    of identity, so the machine drafts and the human decides.
    """
    from tracekite.db.artifact_reader import read_claims
    from tracekite.services.linker.alias_suggestions import suggest_aliases
    from tracekite.services.linker.base import load_aliases
    from tracekite.services.linker.engine import link

    claims = [c for p in args.artifacts for c in read_claims(p)]
    result = link(claims, run_id="linkrun_suggest", now=args.now)
    report = suggest_aliases(claims, result.services, load_aliases())
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_reverify(args) -> int:
    """Does the cited line still say that?

    Compares an artifact's citations against the CURRENT tree and
    downgrades edges built on rot — never deletes them. Exit 2 when not a
    single citation verifies: that is a mis-pointed --repo-root, and
    downgrading the whole graph on it would be self-inflicted rot.
    """
    import os

    from tracekite.db.artifact_reader import read_claims
    from tracekite.services.evidence_reverify import downgrade_stale, reverify
    from tracekite.services.linker.base import load_confidence
    from tracekite.services.linker.engine import link

    def read_file(path: str) -> str | None:
        full = os.path.join(args.repo_root, path)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return None

    claims = [c for p in args.artifacts for c in read_claims(p)]
    report = reverify(claims, read_file)
    if report["counts"]["stale"] and not report["counts"]["ok"]:
        json.dump({"error": "no citation verified; is --repo-root right?",
                   **report["counts"]}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 2

    result = link(claims, run_id="linkrun_reverify", now=args.now)
    downgrades = downgrade_stale(result.edges, report["stale"],
                                 load_confidence())
    json.dump({"citations": report["counts"], "stale": report["stale"],
               **downgrades}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _link_artifacts(paths, run_id: str, now: str):
    """Link a set of artifacts into one graph. The compaction §3.4 describes.

    Claims only: linking needs none of the graph the artifacts carry,
    and reading it anyway made memory grow with estate size, not claim
    count.
    """
    from tracekite.db.artifact_reader import read_claims
    from tracekite.services.linker.engine import link

    return link([c for p in paths for c in read_claims(p)],
                run_id=run_id, now=now)


def cmd_pr(args) -> int:
    """Which consumers this branch breaks, with a file and line for each.

    Two compactions, diffed. `--changed-repo` is what the caller knows from
    git and this does not: without it every loss is reported and none is
    attributed, which is degraded and says so rather than guessing that the
    provider is always at fault.
    """
    from tracekite.services.linker.impact import as_comment, impact

    base = _link_artifacts(args.base, "linkrun_pr_base", args.now)
    head = _link_artifacts(args.head, "linkrun_pr_head", args.now)
    result = impact(base.edges, head.edges,
                    changed_repos=set(args.changed_repo)
                    if args.changed_repo else None)

    if args.comment:
        sys.stdout.write(as_comment(result) + "\n")
    else:
        json.dump(result.as_dict(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    # Non-zero only for breaks this branch caused: a consumer that changed its
    # own code and lost an edge did that to itself, and failing the build for
    # it teaches people to ignore the check.
    return 1 if result.blocking else 0


def cmd_drift(args) -> int:
    """Declared contracts vs observed ones, both sides cited.

    Exits 1 when either drift direction is non-empty, so a CI step can
    hold a service to its own spec.
    """
    from tracekite.db.artifact_reader import read_claims

    if args.base:
        # Temporal mode: the provider reshaped an operation between
        # two commits and consumers kept calling the old shape.
        from tracekite.services.linker.contract_drift import contract_drift

        base = [c for p in args.base for c in read_claims(p)]
        head = [c for p in args.artifacts for c in read_claims(p)]
        report = contract_drift(base, head)
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1 if report["drifted"] else 0

    from tracekite.services.linker.reconciliation import reconcile

    claims = [c for p in args.artifacts for c in read_claims(p)]
    report = reconcile(claims)
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    drifted = any(report[section][direction]
                  for section in ("http", "grpc", "topics")
                  for direction in ("declared_not_observed",
                                    "observed_not_declared"))
    return 1 if drifted else 0


def cmd_reviews(args) -> int:
    """Operator review decisions as labelled data."""
    from tracekite.services.linker.review_labels import review_labels

    labels = review_labels()
    json.dump({**labels,
               "counts": {k: len(v) for k, v in labels.items()}},
              sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_coverage(args) -> int:
    """Per-language extraction coverage.

    Declared in one module and pinned by tests, so a green cell means the
    extractor actually extracts. Declined languages carry their reason —
    an absent row would be indistinguishable from a forgotten one.
    """
    from tracekite.services.extraction_coverage import coverage_report

    json.dump(coverage_report(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_resolvers(args) -> int:
    """Print the declared resolver order.

    Which resolvers run and in what order decides what the graph can contain,
    so it is something a host should be able to read rather than infer from
    where a name sits in a tuple — particularly after registering one of its
    own and needing to know where it landed.
    """
    from tracekite.services.linker.engine import declared_order

    json.dump({"resolvers": declared_order()}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_health(args) -> int:
    """Report whether the engine can answer correctly.

    Exits non-zero when the engine would refuse to run, so a CI step can gate
    on it rather than discovering the problem mid-scan.
    """
    from tracekite import engine_config
    from tracekite.engine_health import FAILED, health

    engine_config.configure(graph_hmac_key=args.hmac_key)
    report = health()
    json.dump(report.as_dict(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 1 if report.status == FAILED else 0


def cmd_diff(args) -> int:
    """What a change did to the graph.

    Exits 1 when the graph moved, so a CI step can fail a PR that changes
    edges without saying so — the point is that a resolver change is
    reviewable by its effect, not only by its code.
    """
    from tracekite.db.artifact_diff import diff_artifacts

    diff = diff_artifacts(args.before, args.after)
    json.dump(diff.as_dict(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 1 if (diff.edges.changed or diff.nodes_added
                 or diff.nodes_removed) else 0
