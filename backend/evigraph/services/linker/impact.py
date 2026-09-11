"""Who a change breaks, and how we know.

The question this whole tool exists to answer, asked about a branch: given the
graph at the base commit and the graph at the head commit, which consumers
lost something they were depending on.

It is a diff of two link runs and nothing cleverer, which is exactly why
determinism is load-bearing rather than tidy — without byte-identical output
for identical input, every removed edge here is noise (architecture §3.4).

**Cause is reported, not inferred.** An edge can disappear because the
provider deleted a route, or because the consumer deleted the call, or because
a resolver stopped matching. Those are different findings and the third is a
bug in Evigraph, not a break. So each loss carries which side's repositories
changed, and a loss where *neither* side changed is flagged rather than
reported as a break — an edge that vanished with no source change is a
regression in the tool and must not be served to a reviewer as somebody's
fault.

**Every break cites a file and a line on the consumer side.** That is the
difference between a PR comment somebody acts on and one they learn to
ignore: "orders-service breaks" is an accusation, "orders-service breaks at
src/billing_client.py:14" is a work item.
"""

from dataclasses import dataclass, field

from evigraph.services.linker.history import changed_between, edge_key


@dataclass(frozen=True)
class Break:
    """One consumer losing one thing it depended on."""

    consumer: str
    lost: str
    edge_type: str
    # `file:line` on the consumer's side. An entry with none is not emitted;
    # see `_consumer_evidence`.
    evidence: tuple[str, ...]
    consumer_repo: str
    provider_repo: str
    # Which side of the edge sits in a repository this change touched.
    provider_changed: bool
    consumer_changed: bool
    # The removed edge's confidence: how sure the tool is that this
    # consumer was really depending on what vanished.
    confidence: float = 0.0

    @property
    def caused_by_this_change(self) -> bool:
        """Whether the provider side is what moved.

        A consumer that changed its own code and lost an edge did that to
        itself; reporting it as breakage would train reviewers to dismiss the
        report, which costs more than the finding is worth.
        """
        return self.provider_changed and not self.consumer_changed

    def as_dict(self) -> dict:
        return {
            "consumer": self.consumer, "lost": self.lost,
            "type": self.edge_type, "evidence": list(self.evidence),
            "consumer_repo": self.consumer_repo,
            "provider_repo": self.provider_repo,
            "caused_by_this_change": self.caused_by_this_change,
        }


@dataclass
class Impact:
    """What a branch does to the graph."""

    breaks: list[Break] = field(default_factory=list)
    added: list[dict] = field(default_factory=list)
    unexplained: list[dict] = field(default_factory=list)
    counters: dict = field(default_factory=dict)

    @property
    def blocking(self) -> list[Break]:
        return [b for b in self.breaks if b.caused_by_this_change]

    def risk(self) -> dict:
        """Blast radius x confidence, as one number per PR.

        Each blocking break contributes its edge's confidence, so the score
        is the number of broken dependencies weighted by how sure the tool
        is about each — thirty certain breaks outscore thirty maybes, and
        one maybe scores near zero instead of crying wolf. `blast` is the
        distinct consumer repos, kept separate because "how big" and "how
        sure" answer different questions and folding them into one number
        loses the one the reader needed.
        """
        blocking = self.blocking
        return {
            "score": round(sum(b.confidence for b in blocking), 2),
            "blast_repos": len({b.consumer_repo for b in blocking
                                if b.consumer_repo}),
            "breaks": len(blocking),
        }

    def as_dict(self) -> dict:
        return {
            "breaks": [b.as_dict() for b in self.breaks],
            "added": self.added,
            # Edges that vanished with neither side changing. A regression in
            # the resolver, not somebody's pull request — surfaced separately
            # so it is never presented as a break.
            "unexplained": self.unexplained,
            "risk": self.risk(),
            "counters": dict(sorted(self.counters.items())),
        }


def _consumer_evidence(edge) -> tuple[str, ...]:
    """The `file:line` citations on the calling side, each once.

    Evidence carries both sides, and the consumer's is what a reviewer needs
    to open. Two resolvers corroborating one edge fuse into it and their
    evidence concatenates, so the same line arrives twice — one piece of work,
    printed twice, which reads like two. Distinct call sites survive: order is
    preserved and only exact repeats are dropped.
    """
    seen, out = set(), []
    for citation in (getattr(edge, "evidence", None) or []):
        text = str(citation)
        if ":" in text and text not in seen:
            seen.add(text)
            out.append(text)
    return tuple(out)


def impact(base_edges: list, head_edges: list, *,
           changed_repos: set[str] | None = None) -> Impact:
    """Which consumers a change breaks, with a citation for each.

    `changed_repos` is the set of repositories this branch touched, which the
    caller knows from git and this does not. Given it, each loss can say
    whether the provider or the consumer moved; without it, every loss is
    reported and none is attributed — degraded, and visibly so, rather than
    quietly guessing that the provider is always at fault.
    """
    changed = changed_repos if changed_repos is not None else set()
    attributing = changed_repos is not None
    delta = changed_between(base_edges, head_edges)
    result = Impact()

    for edge in delta["removed"]:
        evidence = _consumer_evidence(edge)
        consumer_repo = str(getattr(edge, "source_repo_id", "") or "")
        provider_repo = str(getattr(edge, "target_repo_id", "") or "")
        provider_moved = provider_repo in changed
        consumer_moved = consumer_repo in changed

        if not evidence:
            # An edge with no citation is one this tool should not have
            # emitted (I6). Counted here rather than reported as a break,
            # because a break nobody can open is not actionable.
            result.counters["impact.uncitable"] = \
                result.counters.get("impact.uncitable", 0) + 1
            continue

        if attributing and not (provider_repo and consumer_repo):
            # A rendezvous node belongs to no repository — `global:Http:...`
            # is the contract two repos met on, not a thing either owns. So
            # "the provider did not change" is not a conclusion available
            # here; the honest answer is that this edge cannot be attributed,
            # which is neither breakage nor a regression.
            result.counters["impact.unattributable"] = \
                result.counters.get("impact.unattributable", 0) + 1
            continue

        if attributing and not provider_moved and not consumer_moved:
            result.unexplained.append({
                "consumer": edge.source_id, "lost": edge.target_id,
                "type": edge.type,
                "why": "neither side's repository changed in this branch, so "
                       "this edge disappeared for a reason inside Evigraph",
            })
            result.counters["impact.unexplained"] = \
                result.counters.get("impact.unexplained", 0) + 1
            continue

        result.breaks.append(Break(
            consumer=edge.source_id, lost=edge.target_id, edge_type=edge.type,
            evidence=evidence, consumer_repo=consumer_repo,
            provider_repo=provider_repo,
            confidence=float(getattr(edge, "confidence", 0.0) or 0.0),
            # With nothing to attribute against, every loss is reported and
            # marked provider-caused so none is silently dropped.
            provider_changed=provider_moved or not attributing,
            consumer_changed=consumer_moved,
        ))

    result.added = [
        {"consumer": e.source_id, "gained": e.target_id, "type": e.type,
         "evidence": list(_consumer_evidence(e))}
        for e in delta["added"]]
    result.counters["impact.breaks"] = len(result.breaks)
    result.counters["impact.added"] = len(result.added)
    result.counters["impact.unchanged"] = len(delta["kept"])
    return result


def as_comment(result: Impact, *, limit: int = 20) -> str:
    """The pull-request comment.

    Truncation is stated. A comment that silently showed twenty of forty
    breaks would be read as "these are the breaks", and the reader would ship
    the other twenty.
    """
    blocking = result.blocking
    if not blocking and not result.unexplained:
        return ("**Evigraph**: no consumer loses a connection in this change "
                f"({result.counters.get('impact.unchanged', 0)} edges "
                f"unchanged, {len(result.added)} added). Risk: 0.")

    # Grouped by citation, not by consumer. One deleted route removes the
    # Service-to-Service rollup, the name-level edge and the File-to-contract
    # edge — three node ids, one line of code, one thing to fix. Listing them
    # separately reads as three breaks and makes the comment untrustworthy;
    # grouping on the evidence collapses them without deciding which of the
    # three node ids is the "real" one.
    groups: dict[tuple[str, ...], list[Break]] = {}
    for item in blocking:
        groups.setdefault(item.evidence, []).append(item)

    risk = result.risk()
    lines = [f"**Evigraph**: {len(groups)} connection(s) lost across "
             f"{risk['blast_repos']} repo(s). Risk: {risk['score']} "
             f"({risk['breaks']} break(s), confidence-weighted)."]
    for citation in sorted(groups)[:limit]:
        losses = groups[citation]
        repos = sorted({b.consumer_repo for b in losses if b.consumer_repo})
        headline = repos[0] if repos else losses[0].consumer
        lines.append(f"\n- **{headline}** "
                     f"loses `{sorted({b.lost for b in losses})[0]}`")
        for line in citation:
            lines.append(f"  - `{line}`")
        others = sorted({b.consumer for b in losses} - {headline})
        if others:
            lines.append(f"  - _also recorded as: {', '.join(others)}_")

    if len(groups) > limit:
        lines.append(f"\n_{len(groups) - limit} further connection(s) not "
                     f"shown._")
    if result.unexplained:
        lines.append(
            f"\n_{len(result.unexplained)} edge(s) disappeared with neither "
            "side changing — that is a regression in Evigraph, not in this "
            "branch._")
    return "\n".join(lines)


__all__ = ["Break", "Impact", "as_comment", "edge_key", "impact"]
