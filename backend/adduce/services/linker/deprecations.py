"""Who still calls what someone marked deprecated.

An `@Deprecated` annotation is a provider's intention; whether it is safe to
act on is a fact about the *consumers*, and that fact lives in the graph
this tool already built. The report answers the two questions a deprecation
actually raises, in one pass:

* **Consumers listed** — the migration work list, each with the file and
  line to change. A deprecation with forty callers is a project; the report
  is what makes it one instead of a surprise.
* **No consumers** — permission to delete. Reported explicitly rather than
  by omission, because a contract absent from the report is
  indistinguishable from one the report never considered.

Only *served* consumption counts. A `candidate` edge is excluded from
default answers everywhere else; listing it here as a live consumer would
block a deletion on evidence the tool itself declined to assert.
"""


def deprecation_report(edges: list, rendezvous: list) -> list[dict]:
    """Every deprecated contract, with its live consumers cited.

    Pure over one link run's output — no store, no server — so both
    surfaces get the same answer (architecture §2). Sorted throughout:
    the report is diffed between runs to see migrations progressing, and
    an order that shifted underneath would read as change where none
    happened.
    """
    deprecated = [spec for spec in rendezvous
                  if spec.props.get("deprecated")]
    if not deprecated:
        return []

    consumers_of: dict[str, list[dict]] = {}
    for edge in edges:
        if edge.status != "active" \
                or edge.type not in ("INVOKES", "UI_CALLS"):
            continue
        consumers_of.setdefault(edge.target_id, []).append({
            "consumer": edge.source_id,
            "repo": str(getattr(edge, "source_repo_id", "") or ""),
            "evidence": sorted(set(edge.evidence or [])),
        })

    report = []
    for spec in sorted(deprecated, key=lambda s: s.node_id):
        consumers = sorted(consumers_of.get(spec.node_id, []),
                           key=lambda c: (c["repo"], c["consumer"]))
        report.append({
            "contract": spec.node_id,
            "method": spec.props.get("method", ""),
            "path": spec.props.get("path_template", ""),
            "providers": list(spec.props.get("repo_ids", [])),
            "live_consumers": consumers,
            # Stated, not implied: an empty list means "measured and none
            # found", which is the answer that permits deletion.
            "safe_to_remove": not consumers,
        })
    return report
