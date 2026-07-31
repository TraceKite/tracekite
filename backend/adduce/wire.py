"""The published wire contract: what a host may depend on.

These models are the boundary. Everything inside the engine may be refactored
freely; anything shaped like these has consumers who did not write it — a CLI
piping to `jq`, a CI job diffing two runs, a host that stored last week's
artifact and expects to read it today.

**Versioning.** `WIRE_VERSION` is semantic and travels in every payload.
A field added with a default is a minor bump. Removing a field, renaming one,
narrowing a type, or changing what a value means is a **major** bump, because
each silently breaks a reader that is still doing the old thing. When in doubt
it is major: a consumer that crashes is better off than one that misreads.

Emitted as JSON Schema by `json_schemas()`, so a consumer in another language
can validate without running Python.
"""

from pydantic import BaseModel, Field

WIRE_VERSION = "1.3.1"


class EdgeRecord(BaseModel):
    """One connection, and how it is known.

    `evidence` is not decoration. An edge without a `file:line` on both sides
    is precisely what this tool refuses to emit, so the field is required and
    the contract says so.
    """

    type: str
    source: str
    target: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: str
    evidence: list[str]


class ScanReport(BaseModel):
    """What one repository yielded. No edges — scanning cannot know them."""

    wire_version: str = WIRE_VERSION
    repo_id: str
    nodes: int
    edges: int
    claims: dict[str, int]
    coverage: dict[str, str]
    # What was looked for and not found, and whether that absence is
    # evidence. A field added with a default: minor bump, old readers keep
    # working (see the SemVer policy above).
    absence: dict = Field(default_factory=dict)


class LinkReport(BaseModel):
    """What one link run produced, including what it declined to answer.

    `counters` is required and may not be omitted when empty: a report
    carrying edges but no counters has hidden every decline, which is the one
    failure mode this project treats as worse than being wrong out loud.
    """

    wire_version: str = WIRE_VERSION
    run_id: str
    repos: list[str]
    claims_loaded: int
    services: list[str]
    edges: list[EdgeRecord]
    counters: dict[str, int]


class HistoryReport(BaseModel):
    """When each edge existed, across an ordered commit series.

    The range is *derived* from the artifacts, never stored on an edge —
    architecture §3.4. `commits` is echoed back so a reader can tell which
    series produced these ranges: the same edge over a different series is a
    different answer, and a report that omitted the input would look
    authoritative about a graph nobody specified.
    """

    wire_version: str = WIRE_VERSION
    commits: list[str]
    edges: list[dict]


class DeprecationReport(BaseModel):
    """Every deprecated contract and who still calls it.

    An empty `live_consumers` inside an entry is data — measured, none
    found, safe to remove — which is why entries are present even when
    empty rather than omitted.
    """

    wire_version: str = WIRE_VERSION
    contracts: list[dict]


class ConsumerHistoryReport(BaseModel):
    """Who depended on one target, per commit.

    `found: false` carries `candidates` instead of an empty history: an
    unknown target must not read as "nobody depends on it".
    """

    wire_version: str = WIRE_VERSION
    target: str
    found: bool
    commits: list[str]
    history: list[dict] = Field(default_factory=list)
    current_consumers: list[str] = Field(default_factory=list)
    former_consumers: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)


class ExplainReport(BaseModel):
    """Why one edge exists — or an explicit statement that it does not."""

    wire_version: str = WIRE_VERSION
    found: bool
    edges: list[dict] = Field(default_factory=list)
    source: str = ""
    target: str = ""
    candidates: list[str] = Field(default_factory=list)


PUBLISHED = {
    "ScanReport": ScanReport,
    "LinkReport": LinkReport,
    "ExplainReport": ExplainReport,
    "DeprecationReport": DeprecationReport,
    "ConsumerHistoryReport": ConsumerHistoryReport,
    "HistoryReport": HistoryReport,
    "EdgeRecord": EdgeRecord,
}


def json_schemas() -> dict:
    """Every published model as JSON Schema, under one versioned envelope."""
    return {
        "wire_version": WIRE_VERSION,
        "schemas": {name: model.model_json_schema()
                    for name, model in sorted(PUBLISHED.items())},
    }
