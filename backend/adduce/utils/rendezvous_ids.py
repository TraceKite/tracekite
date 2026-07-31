"""The rendezvous node id vocabulary, in one place.

Sibling of `canonical.py` (rendezvous keys) and `evidence.py` (evidence
strings): each of this project's string vocabularies gets exactly one
module that knows how to spell it.

Before this existed the twenty construction sites were spread across ten
resolvers and two routes, and two of those pairs were exact duplicates —
`routes/links.py` rebuilt `r3_library`'s library id and
`routes/trace.py` rebuilt `r6_topic`'s topic id. That is the expensive
kind of duplication rather than the harmless kind: a reader that spells
an id differently from the writer finds nothing, so the failure is an
empty answer, not an error. Nobody sees a stack trace; they see a graph
that looks like it has no topics.

Pure string builders, no imports, no I/O — so every layer may use them
and the writer and the reader cannot drift apart.

`architecture.md` §3.2 owns what a rendezvous *is*; this owns only how
its id is spelled. Adding a label here is the deliberate act: the
`check_invariants.py` I4 pass rejects a `global:` id built anywhere else.
"""

_PREFIX = "global"


def service_id(name: str) -> str:
    """A Service cluster: the identity R0 mints and everything else joins on."""
    return f"{_PREFIX}:Service:{name}"


def svcname_id(scope: str, name: str) -> str:
    """A scoped service NAME claim, distinct from the Service it resolves to."""
    return f"{_PREFIX}:SvcName:{scope}:{name}"


def module_id(module: str) -> str:
    return f"{_PREFIX}:Module:{module}"


def deployment_unit_id(namespace: str, kind: str, name: str) -> str:
    """Lowercased, because Kubernetes object references are case-insensitive
    in practice and two spellings of one workload must not become two nodes."""
    return f"{_PREFIX}:DeploymentUnit:{namespace}/{kind}/{name}".lower()


def http_contract_id(scope: str, method: str, template: str) -> str:
    return f"{_PREFIX}:Http:{scope}:{method}:{template}"


def topic_id(key: str) -> str:
    return f"{_PREFIX}:Topic:{key}"


def library_id(key: str) -> str:
    return f"{_PREFIX}:Lib:{key}"


def dataset_id(key: str) -> str:
    return f"{_PREFIX}:Data:{key}"


def team_id(key: str) -> str:
    return f"{_PREFIX}:Team:{key}"


def grpc_operation_id(key: str) -> str:
    """`package.Service/Rpc` — globally unique by construction, which is why
    R5 needs no service hint to join on it."""
    return f"{_PREFIX}:Op:grpc:{key}"


def graphql_operation_id(key: str) -> str:
    """`Type.field` carries no package, so unlike gRPC it is only unique
    within a schema; R8 declines when two subgraphs claim one."""
    return f"{_PREFIX}:Op:graphql:{key}"


def agent_operation_id(key: str) -> str:
    """MCP/A2A operations: the key already carries its own `mcp:`/`a2a:`
    namespace, so no transport segment is added here."""
    return f"{_PREFIX}:Op:{key}"
