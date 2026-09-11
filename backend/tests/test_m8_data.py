"""M8 data & pipelines: extractors -> dataset/db claims -> R10 -> lineage.

The precision core is the single-declarer rule: a bare SQL table name joins
across repos only when exactly one repo declares it (migration/ORM/dbt
schema). Distinctive namespaces (ES indices, Dynamo tables, S3 buckets,
Unity Catalog three-part names) join freely.
"""

from types import SimpleNamespace

from evigraph.parsers.pipeline_parser import parse_databricks_notebook, parse_dbt_model
from evigraph.services.ingest_claims import (
    emit_data_site_claims, emit_migration_claims, emit_pipeline_claims,
)
from evigraph.services.ingest_source import IngestSink
from evigraph.services.linker import r0_alias, r6_topic, r10_dataset
from evigraph.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput, load_confidence,
)

JPA_ENTITY = """
import jakarta.persistence.Entity;
import jakarta.persistence.Table;

@Entity
@Table(name = "owners")
public class Owner { private Long id; }
"""

FLYWAY_SQL = """
CREATE TABLE owners (id BIGINT PRIMARY KEY, name VARCHAR(255));
ALTER TABLE owners ADD COLUMN email VARCHAR(255);
"""

PY_READER = """
import psycopg2

def load(conn):
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM owners WHERE id = %s", (1,))
    return cur.fetchall()
"""

ES_CLIENT = """
from elasticsearch import Elasticsearch
es = Elasticsearch()
es.index(index="visits", document={"a": 1})
res = es.search(index="visits", query={"match_all": {}})
"""

NOTEBOOK = """# Databricks notebook source
# MAGIC %run /pipelines/shared_setup

df = spark.read.table("main.sales.orders")
events = (spark.readStream.format("kafka")
    .option("subscribe", "order-events")
    .load())
df.write.mode("overwrite").saveAsTable("main.sales.daily_totals")
"""


def _file(path, language=None):
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


def _source(repo_id, path, content, language):
    sink = IngestSink()
    emit_data_site_claims(repo_id, _file(path, language), content,
                          f"file:{path}", sink)
    return _claims(sink, repo_id)


def _migration(repo_id, path, content):
    sink = IngestSink()
    emit_migration_claims(repo_id, _file(path), content, f"file:{path}", sink)
    return _claims(sink, repo_id)


def run_linker(claims):
    ctx = LinkContext("linkrun_test", load_confidence(), {})
    ctx.known_repos = {c.repo_id for c in claims}
    index = ClaimIndex(claims)
    out = ResolverOutput()
    for module in (r0_alias, r10_dataset, r6_topic):
        out.extend(module.resolve(index, ctx))
    return ctx, out


def edges_of(out, edge_type):
    return [e for e in out.edges if e.type == edge_type]


class TestSingleDeclarerRule:
    def test_declared_table_anchors_cross_repo_readers(self):
        claims = (_migration("repo_owners",
                             "db/migration/V2__create_owners.sql", FLYWAY_SQL)
                  + _source("repo_owners", "src/model/Owner.java", JPA_ENTITY,
                            "java")
                  + _source("repo_reports", "src/load.py", PY_READER, "python"))
        ctx, out = run_linker(claims)
        datasets = [r for r in out.rendezvous if r.label == "Dataset"]
        assert [d.props["key"] for d in datasets] == ["table:owners"]
        assert datasets[0].props["declared_by"] == "repo_owners"
        reads = [e for e in edges_of(out, "READS_FROM")
                 if e.source_repo_id == "repo_reports"]
        assert reads and reads[0].target_repo_id == "repo_owners"
        assert reads[0].cross_repo

    def test_undeclared_shared_table_name_declines(self):
        claims = (_source("repo_a", "src/a.py", PY_READER, "python")
                  + _source("repo_b", "src/b.py", PY_READER, "python"))
        ctx, out = run_linker(claims)
        assert ctx.counters["r10.ambiguous_table"] == 1
        assert not [r for r in out.rendezvous if r.label == "Dataset"]

    def test_same_repo_references_still_join(self):
        claims = _source("repo_a", "src/a.py", PY_READER, "python")
        ctx, out = run_linker(claims)
        assert [r.props["key"] for r in out.rendezvous] == ["table:owners"]


class TestDistinctiveNamespaces:
    def test_es_index_joins_freely_across_repos(self):
        writer = _source("repo_ingestor", "src/w.py", ES_CLIENT, "python")
        reader = _source("repo_search", "src/r.py", ES_CLIENT, "python")
        ctx, out = run_linker(writer + reader)
        keys = {r.props["key"] for r in out.rendezvous if r.label == "Dataset"}
        assert keys == {"index:visits"}
        assert ctx.counters["r10.writes"] >= 2
        assert ctx.counters["r10.reads"] >= 2


class TestPipelines:
    def test_notebook_lineage_and_kafka_join(self):
        pipeline = parse_databricks_notebook("etl/orders_nb.py", NOTEBOOK)
        sink = IngestSink()
        emit_pipeline_claims("repo_etl", _file("etl/orders_nb.py"), pipeline,
                             "file:nb", sink)
        ctx, out = run_linker(_claims(sink, "repo_etl"))
        keys = {r.props["key"] for r in out.rendezvous if r.label == "Dataset"}
        assert "wh:main.sales.orders" in keys
        assert "wh:main.sales.daily_totals" in keys
        assert any(k.startswith("pipeline:") for k in keys)
        # The kafka read surfaced as a topic claim joins VQ3's world.
        topic = [r for r in out.rendezvous if r.label == "Topic"]
        assert [t.props["key"] for t in topic] == ["kafka:order-events"]
        writes = edges_of(out, "WRITES_TO")
        assert any(e.claim_key == "wh:main.sales.daily_totals" for e in writes)

    def test_dbt_model_reads_refs_and_sources(self):
        model = parse_dbt_model(
            "models/marts/daily_totals.sql",
            "select * from {{ ref('stg_orders') }} "
            "join {{ source('raw', 'payments') }} using (order_id)")
        sink = IngestSink()
        emit_pipeline_claims("repo_dbt", _file("models/marts/daily_totals.sql"),
                             model, "file:model", sink)
        claims = _claims(sink, "repo_dbt")
        reads = {c.key for c in claims if c.direction == "consumes"}
        assert "model:stg_orders" in reads
        assert "table:raw.payments" in reads
        writes = {c.key for c in claims if c.direction == "provides"}
        assert "model:daily_totals" in writes


class TestDeclarationTiers:
    def test_migration_beats_literal_confidence(self):
        claims = (_migration("repo_owners",
                             "db/migration/V2__create_owners.sql", FLYWAY_SQL)
                  + _source("repo_reports", "src/load.py", PY_READER, "python"))
        _, out = run_linker(claims)
        declared = [e for e in edges_of(out, "WRITES_TO")
                    if e.extra_props.get("declares")]
        reads = edges_of(out, "READS_FROM")
        assert declared and reads
        assert declared[0].confidence > reads[0].confidence
