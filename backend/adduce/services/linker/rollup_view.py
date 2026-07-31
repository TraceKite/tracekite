"""Roll the service map up to groups a person can look at.

A thousand services is not a diagram, it is a haystack: per-service
rendering stops being navigation somewhere around a hundred nodes. This
folds services into groups — by ownership when the estate declares it, by
the name's domain prefix when it does not — and rolls the edges up between
groups, so the first screen of a large estate is dozens of boxes whose
edges carry weights, not thousands of overlapping lines.

Nothing is invented on the way up. A group edge's weight is the count of
the service edges inside it, its confidence is their *minimum* — the
chain-of-custody rule: an aggregate is only as trustworthy as its least
trustworthy member, and taking the mean would let one weak edge hide
inside strong neighbours. Intra-group calls are folded into the group's
own `internal_edges` count rather than dropped, because a group that
looks quiet from outside may be the busiest thing in the estate.

Services with no owner land in an explicit `(unowned)` group, never
scattered or omitted: at estate scale, "who owns this" being unanswered
is a finding.
"""

from collections import defaultdict


def domain_of(name: str) -> str:
    """The name's first hyphen segment: billing-api and billing-worker
    share `billing`. A name with no hyphen is its own domain."""
    return (name or "").split("-", 1)[0] or "(unnamed)"


def aggregate_service_map(services: list[dict], edges: list[dict], *,
                          by: str = "domain",
                          ownership: dict[str, str] | None = None) -> dict:
    """Fold a service map into group boxes and rolled-up edges.

    `services` rows carry `id`/`name`; `edges` rows carry
    `source`/`target`/`confidence` (+ optional `type`). `ownership` maps a
    service id to its team and is required for `by="team"` — passing none
    puts everything in `(unowned)`, which is the honest rendering of an
    estate that declared no owners, not an error.
    """
    if by not in ("domain", "team"):
        raise ValueError(f"unknown grouping {by!r}: domain or team")

    def group_of(service: dict) -> str:
        if by == "team":
            return (ownership or {}).get(service["id"]) or "(unowned)"
        return domain_of(service.get("name") or service["id"])

    member_group: dict[str, str] = {}
    groups: dict[str, dict] = {}
    for service in services:
        name = group_of(service)
        member_group[service["id"]] = name
        group = groups.setdefault(name, {
            "id": name, "services": [], "internal_edges": 0})
        group["services"].append(service.get("name") or service["id"])

    rolled: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"weight": 0, "min_confidence": 1.0, "types": set()})
    dropped = 0
    for edge in edges:
        source = member_group.get(edge["source"])
        target = member_group.get(edge["target"])
        if source is None or target is None:
            # An edge endpoint that is not a known service (a rendezvous
            # node, a repo) has no group; counted rather than folded into
            # some box it does not belong to.
            dropped += 1
            continue
        if source == target:
            groups[source]["internal_edges"] += 1
            continue
        group = rolled[(source, target)]
        group["weight"] += 1
        group["min_confidence"] = min(group["min_confidence"],
                                      float(edge.get("confidence") or 0.0))
        if edge.get("type"):
            group["types"].add(edge["type"])

    for group in groups.values():
        group["services"].sort()
        group["size"] = len(group["services"])

    return {
        "by": by,
        "groups": sorted(groups.values(), key=lambda g: g["id"]),
        "edges": [{"source": s, "target": t, "weight": v["weight"],
                   "min_confidence": round(v["min_confidence"], 4),
                   "types": sorted(v["types"])}
                  for (s, t), v in sorted(rolled.items())],
        "non_service_edges": dropped,
    }


def ownership_from_rows(rows: list) -> dict:
    """Service -> owning team, from (service, team) rows sorted by both.

    The tie-break is the reason this is not a comprehension in the route:
    two teams claiming one service is a real situation, and which one the
    map shows must be decided the same way for every caller. First in
    sorted order wins — arbitrary, but identical for the app and for a
    library host, which is the property that matters. Picking differently
    per surface would make the same estate render two ownership stories.
    """
    ownership: dict[str, str] = {}
    for row in rows:
        ownership.setdefault(row["service"], row["team"])
    return ownership
