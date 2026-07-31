"""When each edge existed, derived from the artifact series.

Architecture §3.4 is normative here and it rules out the obvious design: the
time dimension is **deliberately not a field on the edge**. Each repo artifact
is content-addressed and stamped with its `head_sha`, so "the graph at commit
X" is a compaction of the artifacts at X — point-in-time falls out of the
artifact model at no storage cost and with no schema change.

The roadmap's wording for G1 — "edges valid over commit ranges" — reads like
an interval stored per edge. It is satisfied here as a *derived* range: the
served answer carries a validity range, and nothing in storage does. Storing
one would mean every relink rewrites every edge's interval, and an edge whose
interval was rewritten after the fact can no longer be checked against the
artifacts it came from.

**Gaps are preserved.** An edge that appeared at commit A, vanished at B and
returned at C produces two intervals, never one spanning A to C. Collapsing
them would assert the edge existed at B, which is an invented edge wearing a
timestamp — the same defect as any other, and harder to spot because nobody
looks at a date twice.

**Only served edges count.** A `candidate` edge is excluded from default
answers, so treating it as present would report a connection during a period
when the tool would not have shown one. A drop to `candidate` ends an
interval, and the transition is counted rather than smoothed over.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Interval:
    """One unbroken run of commits over which an edge was served."""

    first_commit: str
    last_commit: str
    # Positions in the supplied series, so a caller that knows its own
    # ordering can locate the boundary without matching shas.
    first_index: int
    last_index: int


@dataclass
class EdgeHistory:
    """One edge's identity and every period it existed."""

    type: str
    source: str
    target: str
    intervals: list[Interval] = field(default_factory=list)
    present_at_head: bool = False

    @property
    def reappeared(self) -> bool:
        """Whether the edge came back after being gone.

        Worth its own name: a flapping edge is a different finding from a
        stable one, and usually means the evidence is conditional on something
        the scan cannot see.
        """
        return len(self.intervals) > 1

    def as_dict(self) -> dict:
        return {
            "type": self.type, "source": self.source, "target": self.target,
            "present_at_head": self.present_at_head,
            "reappeared": self.reappeared,
            "intervals": [
                {"first_commit": i.first_commit, "last_commit": i.last_commit,
                 "first_index": i.first_index, "last_index": i.last_index}
                for i in self.intervals
            ],
        }


def edge_key(edge) -> tuple[str, str, str]:
    """What makes two edges across commits the same edge.

    Not evidence, and not confidence. Line numbers move when a file is edited
    above the call site, and confidence changes when a resolver is retuned;
    treating either as identity would report the edge as removed and re-added
    on every unrelated commit.
    """
    return (edge.type, edge.source_id, edge.target_id)


def edge_history(series: list[tuple[str, list]]) -> list[EdgeHistory]:
    """Validity ranges for every edge across an ordered commit series.

    `series` is `[(commit_sha, edges), ...]` **in commit order**, which the
    caller supplies. Artifacts record the commit they were scanned at but not
    its parent, so the order is knowledge this module does not have and will
    not guess — a series sorted wrongly would report every edge as flapping.
    """
    seen: dict[tuple[str, str, str], EdgeHistory] = {}
    open_at: dict[tuple[str, str, str], int] = {}

    for index, (commit, edges) in enumerate(series):
        present = {edge_key(e) for e in edges
                   if getattr(e, "status", "active") == "active"}
        for key in sorted(present):
            history = seen.get(key)
            if history is None:
                history = EdgeHistory(*key)
                seen[key] = history
            if key not in open_at:
                open_at[key] = index
                history.intervals.append(
                    Interval(commit, commit, index, index))
            else:
                last = history.intervals[-1]
                history.intervals[-1] = Interval(
                    last.first_commit, commit, last.first_index, index)

        for key in [k for k in open_at if k not in present]:
            del open_at[key]

    head_index = len(series) - 1
    for key, history in seen.items():
        history.present_at_head = (
            key in open_at
            and history.intervals[-1].last_index == head_index)

    return [seen[k] for k in sorted(seen)]


def consumers_over_time(series: list[tuple[str, list]],
                        target: str) -> dict:
    """Who depended on `target` at each commit — blast radius as data.

    A blast radius is a number until somebody asks "since when": a contract
    that gained thirty consumers this quarter is a different risk from one
    that has carried thirty for years, and only the artifact series can
    tell them apart. Same input contract as `edge_history`: an ordered
    series the caller vouches for.

    An unknown target returns the candidates rather than an empty history —
    empty would read as "measured, and nobody depends on it", which is
    precisely the wrong answer to hand someone deciding whether a removal
    is safe.
    """
    per_commit, seen_targets = [], set()
    for commit, edges in series:
        consumers = set()
        for edge in edges:
            if getattr(edge, "status", "active") != "active":
                continue
            seen_targets.add(edge.target_id)
            if edge.target_id == target:
                consumers.add(edge.source_id)
        per_commit.append({"commit": commit,
                           "consumers": sorted(consumers)})

    if not any(entry["consumers"] for entry in per_commit) \
            and target not in seen_targets:
        return {"found": False, "target": target, "history": [],
                "candidates": sorted(seen_targets)}

    ever = sorted({c for entry in per_commit for c in entry["consumers"]})
    current = set(per_commit[-1]["consumers"]) if per_commit else set()
    return {
        "found": True, "target": target, "history": per_commit,
        # The set a removal breaks today, and the set that ever depended —
        # the difference is who already migrated away.
        "current_consumers": sorted(current),
        "former_consumers": sorted(set(ever) - current),
    }


def changed_between(before: list, after: list) -> dict[str, list]:
    """Which edges a change adds and removes — PR mode's primitive.

    Two compactions, diffed. That is the whole of what architecture §3.4 says
    point-in-time is, and it is why determinism is load-bearing: without
    byte-identical output for identical input, every diff is noise.
    """
    was = {edge_key(e): e for e in before
           if getattr(e, "status", "active") == "active"}
    now = {edge_key(e): e for e in after
           if getattr(e, "status", "active") == "active"}
    return {
        "added": [now[k] for k in sorted(now.keys() - was.keys())],
        "removed": [was[k] for k in sorted(was.keys() - now.keys())],
        "kept": [now[k] for k in sorted(now.keys() & was.keys())],
    }
