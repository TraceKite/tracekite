"""M3 GraphQL: SDL -> claims -> R8 -> cross-repo operation edges.

`Type.field` carries no package, so unlike a protobuf key two teams can define
the same one. R8 therefore treats a multi-repo definition as ambiguous unless
federation metadata says who owns it.
"""

from types import SimpleNamespace

import pytest

from adduce.parsers.graphql_parser import (
    extract_gql_tags, parse_graphql_operations, parse_graphql_schema,
)
from adduce.services.ingest_claims import (
    emit_graphql_claims, emit_graphql_client_claims,
)
from adduce.services.ingest_source import IngestSink
from adduce.services.linker import r0_alias, r8_graphql
from adduce.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput, load_confidence,
)

SDL = '''
"""The owners API."""
# a comment mentioning type GhostType
schema {
  query: Query
  mutation: Mutation
}

type Query {
  owner(id: ID!): Owner
  owners(first: Int): [Owner!]!
}

type Mutation {
  createOwner(input: CreateOwnerInput!): Owner!
}

type Owner @key(fields: "id") {
  id: ID!
  name: String
}

input CreateOwnerInput { name: String! }
'''

OPERATIONS = """
query GetOwner($id: ID!) {
  owner(id: $id) {
    id
    name
    pets { name }
  }
}

mutation AddOwner($input: CreateOwnerInput!) {
  createOwner(input: $input) { id }
}
"""


def _file(path, language="graphql"):
    return SimpleNamespace(path=path, language=language)


def _claims(sink, repo_id):
    records = []
    for node in sink.nodes:
        if node.type != "ContractClaim":
            continue
        extra = node.extra_props
        records.append(ClaimRecord(
            id=node.id, repo_id=repo_id, kind=extra["kind"],
            direction=extra["direction"], key=extra["key"],
            service_hint=extra.get("service_hint"),
            hint_source=extra.get("hint_source", "none"),
            matchable=bool(extra.get("matchable", True)),
            evidence=list(extra.get("evidence") or []),
            attrs=dict(node.metadata or {}),
            evidence_node_id=f"node:{node.id}", evidence_node_type="File",
        ))
    return records


def run_linker(claims):
    ctx = LinkContext("linkrun_test", load_confidence(), {})
    ctx.known_repos = {c.repo_id for c in claims}
    index = ClaimIndex(claims)
    out = ResolverOutput()
    for module in (r0_alias, r8_graphql):
        out.extend(module.resolve(index, ctx))
    return ctx, out


class TestSchemaParsing:
    def test_root_fields_from_query_and_mutation(self):
        schema = parse_graphql_schema("schema.graphql", SDL)
        assert sorted(f.key for f in schema.root_fields) == [
            "Mutation.createOwner", "Query.owner", "Query.owners"]

    def test_non_root_types_do_not_contribute_fields(self):
        # Owner.id is not an entry point; only root operation fields are.
        schema = parse_graphql_schema("schema.graphql", SDL)
        assert not any(f.parent_type == "Owner" for f in schema.root_fields)

    def test_return_types_captured(self):
        schema = parse_graphql_schema("schema.graphql", SDL)
        owners = [f for f in schema.root_fields if f.name == "owners"][0]
        assert owners.return_type == "[Owner!]!"

    def test_federation_key_directive(self):
        schema = parse_graphql_schema("schema.graphql", SDL)
        assert schema.is_federated is True
        owner = [t for t in schema.types if t.name == "Owner"][0]
        assert owner.key_fields == ["id"]

    def test_custom_root_type_names(self):
        schema = parse_graphql_schema("s.graphql", """
schema { query: RootQuery }
type RootQuery { ping: String }
type Query { notTheRoot: String }
""")
        assert [f.key for f in schema.root_fields] == ["RootQuery.ping"]

    def test_comments_and_block_strings_are_ignored(self):
        schema = parse_graphql_schema("s.graphql", SDL)
        assert not any(t.name == "GhostType" for t in schema.types)

    def test_extend_type_marks_federation(self):
        schema = parse_graphql_schema("s.graphql",
                                      "extend type Query { extra: String }")
        assert schema.is_federated is True
        assert schema.types[0].is_extension is True

    def test_malformed_sdl_does_not_raise(self):
        assert parse_graphql_schema("s.graphql", "type Broken {").root_fields == []
        assert parse_graphql_schema("s.graphql", "").types == []


class TestOperationParsing:
    def test_root_fields_of_each_operation(self):
        operations = parse_graphql_operations(OPERATIONS)
        assert [(o.operation, o.name, o.root_fields) for o in operations] == [
            ("query", "GetOwner", ["owner"]),
            ("mutation", "AddOwner", ["createOwner"]),
        ]

    def test_nested_selections_are_not_root_fields(self):
        # `pets` belongs to Owner, not Query.
        [operation, _] = parse_graphql_operations(OPERATIONS)
        assert "pets" not in operation.root_fields
        assert "name" not in operation.root_fields

    def test_gql_template_literal_with_line_offset(self):
        content = "\n\nconst Q = gql`\n  query Get { owner { id } }\n`;\n"
        [operation] = extract_gql_tags(content)
        assert operation.root_fields == ["owner"]
        assert operation.line == 4

    def test_no_tags_yields_nothing(self):
        assert extract_gql_tags("const x = 1;") == []


class TestR8Linking:
    def _estate(self, client_repo="repo_web"):
        server = IngestSink()
        emit_graphql_claims("repo_api", _file("schema.graphql"),
                            {"schema": parse_graphql_schema("schema.graphql", SDL),
                             "operations": []},
                            "file:schema", server)
        client = IngestSink()
        emit_graphql_client_claims(
            client_repo, _file("src/queries.ts", "typescript"),
            "const Q = gql`query GetOwner { owner { id } }`;",
            "file:client", client)
        return _claims(server, "repo_api") + _claims(client, client_repo)

    def test_sdl_yields_one_operation_per_root_field(self):
        ctx, out = run_linker(self._estate())
        keys = {r.props["key"] for r in out.rendezvous
                if r.label == "ContractOperation"}
        assert keys == {"Query.owner", "Query.owners", "Mutation.createOwner"}
        assert ctx.counters["r8.operations"] == 3

    def test_client_operation_invokes_across_repos(self):
        ctx, out = run_linker(self._estate())
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert len(invokes) == 1
        assert invokes[0].target_id == "global:Op:graphql:Query.owner"
        assert invokes[0].source_repo_id == "repo_web"
        assert invokes[0].target_repo_id == "repo_api"
        assert invokes[0].cross_repo is True

    def test_federated_schema_scores_above_bare_field_name(self):
        _, out = run_linker(self._estate())
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert invokes[0].match_type == "graphql_federated"
        assert invokes[0].confidence == pytest.approx(0.95)

    def test_sdl_declaration_is_highest_confidence(self):
        _, out = run_linker(self._estate())
        exposes = [e for e in out.edges if e.type == "EXPOSES"]
        assert exposes and exposes[0].confidence == pytest.approx(0.98)

    def test_same_field_in_two_repos_without_federation_ranks_candidates(self):
        """Ambiguity returns weighted candidates, not silence.

        `Query.user` defined twice with nothing saying who owns it. Picking
        one is still a coin flip and this does not pick — the confidence is
        divided among the possible owners, which puts it below the floor, so
        the edge is written `candidate`: inspectable, excluded from default
        answers, never served as fact.

        The decline is still counted, because to anyone reading active edges
        it remains a decline. A ranked list beats silence only if nobody can
        mistake it for an answer.
        """
        plain = "type Query { user: String }"
        a = IngestSink()
        emit_graphql_claims("repo_a", _file("a.graphql"),
                            {"schema": parse_graphql_schema("a.graphql", plain),
                             "operations": []}, "f", a)
        b = IngestSink()
        emit_graphql_claims("repo_b", _file("b.graphql"),
                            {"schema": parse_graphql_schema("b.graphql", plain),
                             "operations": []}, "f", b)
        client = IngestSink()
        emit_graphql_client_claims(
            "repo_web", _file("q.ts", "typescript"),
            "gql`query { user }`", "f", client)
        ctx, out = run_linker(_claims(a, "repo_a") + _claims(b, "repo_b")
                              + _claims(client, "repo_web"))
        assert ctx.counters["r8.ambiguous_owner"] >= 1

        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert invokes, "silence is exactly what E4 replaces"
        assert all(e.confidence < 0.6 for e in invokes), (
            "a divided score must fall below the floor, or an ambiguous "
            "match would be served as an active edge")
        assert all(not e.target_repo_id for e in invokes), (
            "naming one of several possible owners is the coin flip this "
            "still does not make")

    def test_unmatched_client_operation_counted(self):
        client = IngestSink()
        emit_graphql_client_claims(
            "repo_web", _file("q.ts", "typescript"),
            "gql`query { nonexistentField }`", "f", client)
        ctx, out = run_linker(_claims(client, "repo_web"))
        assert ctx.counters["r8.unmatched"] >= 1
        assert not [e for e in out.edges if e.type == "INVOKES"]
