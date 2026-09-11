"""Data-layer site extraction."""

from evigraph.services.data_extractor import DataSite, extract_data_sites

ES_PY = """\
import os
from elasticsearch import Elasticsearch

es = Elasticsearch(os.environ["ES_URL"])

def find_owners(city):
    return es.search(index="owners", query={"match": {"city": city}})

def reindex(doc):
    es.index(index="owners", document=doc)
    es.bulk(index="owner-audit", operations=[])

def setup():
    es.indices.create(index="owners")

def mirror(target):
    es.index(index=target, document={})           # dynamic -> no name
    es.search(index=os.environ["AUDIT_INDEX"])    # env-var reference
"""

ES_JS = """\
const { Client } = require('@elastic/elasticsearch');
const client = new Client({ node: process.env.ES_URL });

async function findOwners(city) {
  return client.search({ index: 'owners', query: { match: { city } } });
}
async function save(doc) {
  await client.index({ index: 'owners', document: doc });
}
"""

ES_JAVA = """\
import co.elastic.clients.elasticsearch.ElasticsearchClient;
import org.springframework.data.elasticsearch.annotations.Document;

@Document(indexName = "owners")
public class OwnerDoc {}

class OwnerSearch {
    void run(ElasticsearchClient client) throws Exception {
        client.search(s -> s.index("owners").query(q -> q.matchAll(m -> m)), OwnerDoc.class);
        SearchRequest legacy = new SearchRequest("owner-audit");
        IndexRequest req = new IndexRequest("owners");
    }
}
"""

JPA_ENTITY = """\
import jakarta.persistence.Entity;
import jakarta.persistence.Table;

@Entity
@Table(name = "owners")
public class Owner {}

@Entity
public class Visit {
    private Integer id;
}
"""

PRISMA_SCHEMA = """\
model Owner {
  id    Int    @id @default(autoincrement())
  pets  Pet[]

  @@map("owners")
}

model Pet {
  id      Int   @id
  ownerId Int
}
"""

BOTO3_MODULE = """\
import os
import boto3

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

def load_report(key):
    return s3.get_object(Bucket="clinic-reports", Key=key)

def store_photo(path, key):
    s3.upload_file(path, "clinic-media", key)
    s3.put_object(Bucket=os.environ["ARCHIVE_BUCKET"], Key=key, Body=b"")

def owners_table():
    return dynamodb.Table("owners").query(KeyConditionExpression="pk = :p")

def record_visit(item):
    dynamodb.Table("visits").put_item(Item=item)
"""

RAW_SQL_PY = """\
import psycopg2

def owner_visits(conn, owner_id):
    cur = conn.cursor()
    cur.execute(
        \"\"\"SELECT o.first_name, v.visit_date
        FROM owners o
        JOIN visits v ON v.owner_id = o.id
        WHERE o.id = %(owner_id)s\"\"\", {"owner_id": owner_id})
    cur.execute("INSERT INTO audit_log (msg) VALUES (%s)", ("read",))
    cur.execute("UPDATE owners SET last_seen = now() WHERE id = %s", (owner_id,))
    cur.execute("CALL refresh_owner_stats(%s)", (owner_id,))
    cur.execute(f"DELETE FROM {table}")   # dynamic table -> no name
"""


def _by(sites, **want):
    return [s for s in sites
            if all(getattr(s, k) == v for k, v in want.items())]


class TestElasticsearch:
    def test_python_roles_and_declares(self):
        sites = extract_data_sites(ES_PY, "python")
        assert _by(sites, kind="index", name="owners", role="reads")
        assert _by(sites, kind="index", name="owners", role="writes")
        assert _by(sites, kind="index", name="owner-audit", role="writes")
        assert _by(sites, kind="index", name="owners", role="declares")
        assert all(s.system == "elasticsearch" for s in sites if s.kind == "index")

    def test_python_dynamic_and_env_var(self):
        sites = extract_data_sites(ES_PY, "python")
        dyn = _by(sites, kind="index", dynamic=True)
        assert dyn and all(s.name == "" for s in dyn)
        assert any(s.env_var == "AUDIT_INDEX" for s in dyn)

    def test_python_without_client_import_yields_nothing(self):
        sites = extract_data_sites('df.get(index="owners")', "python")
        assert _by(sites, kind="index") == []

    def test_js_client(self):
        sites = extract_data_sites(ES_JS, "javascript")
        assert _by(sites, kind="index", name="owners", role="reads")
        assert _by(sites, kind="index", name="owners", role="writes")

    def test_java_lambda_requests_and_spring_data(self):
        sites = extract_data_sites(ES_JAVA, "java")
        assert _by(sites, name="owners", role="reads", framework="elasticsearch-java")
        assert _by(sites, name="owner-audit", role="reads")
        assert _by(sites, name="owners", role="writes")
        declared = _by(sites, name="owners", role="declares")
        assert declared and declared[0].framework == "spring-data-elasticsearch"

    def test_go_opensearch_struct(self):
        go = ('import "github.com/opensearch-project/opensearch-go/opensearchapi"\n'
              'req := opensearchapi.SearchRequest{Index: []string{"owners"}}\n')
        sites = extract_data_sites(go, "go")
        assert _by(sites, kind="index", name="owners", role="reads",
                   system="opensearch")


class TestOrmTables:
    def test_jpa_explicit_and_inferred(self):
        sites = extract_data_sites(JPA_ENTITY, "java")
        owners = _by(sites, kind="table", name="owners", role="declares")
        assert owners and "inferred" not in owners[0].attrs
        visit = _by(sites, kind="table", name="visit")
        assert visit and visit[0].attrs.get("inferred") is True
        assert visit[0].attrs.get("raw") == "Visit"

    def test_sqlalchemy_and_django(self):
        py = ('class Owner(Base):\n    __tablename__ = "owners"\n\n'
              'pets = Table("pets", metadata, Column("id", Integer))\n'
              'class Meta:\n    db_table = "clinic_visits"\n')
        names = {s.name for s in extract_data_sites(py, "python") if s.kind == "table"}
        assert names == {"owners", "pets", "clinic_visits"}

    def test_prisma_map_and_inferred_model(self):
        sites = extract_data_sites(PRISMA_SCHEMA, "prisma")
        assert _by(sites, name="owners", framework="prisma")[0].attrs == {}
        pet = _by(sites, name="pet", framework="prisma")[0]
        assert pet.attrs.get("inferred") is True and pet.attrs.get("raw") == "Pet"

    def test_typeorm_gorm_efcore(self):
        ts = "@Entity('owners')\nexport class Owner {}\n@Entity()\nexport class Visit {}\n"
        ts_sites = extract_data_sites(ts, "typescript")
        assert _by(ts_sites, name="owners") and _by(ts_sites, name="visit")

        go = 'func (Owner) TableName() string { return "owners" }'
        assert _by(extract_data_sites(go, "go"), name="owners", framework="gorm")

        cs = ('[Table("Owners")]\npublic class Owner {}\n'
              'modelBuilder.Entity<Visit>().ToTable("Visits");\n')
        cs_sites = extract_data_sites(cs, "csharp")
        assert {s.name for s in cs_sites if s.kind == "table"} == {"owners", "visits"}
        assert all(s.role == "declares" for s in cs_sites)


class TestRawSql:
    def test_reads_writes_procs_from_string_literals(self):
        sites = extract_data_sites(RAW_SQL_PY, "python")
        reads = {s.name for s in _by(sites, kind="table", role="reads", system="sql")
                 if not s.attrs.get("procedure")}
        assert reads == {"owners", "visits"}
        writes = {s.name for s in _by(sites, kind="table", role="writes", dynamic=False)}
        assert writes == {"audit_log", "owners"}
        proc = _by(sites, name="refresh_owner_stats")
        assert proc and proc[0].attrs.get("procedure") is True

    def test_dynamic_table_position_has_no_name(self):
        sites = extract_data_sites(RAW_SQL_PY, "python")
        dyn = _by(sites, kind="table", dynamic=True)
        assert dyn and dyn[0].name == ""

    def test_prose_with_from_is_not_sql(self):
        sites = extract_data_sites('msg = "greetings from owners of pets"', "python")
        assert _by(sites, kind="table") == []

    def test_sql_language_whole_file(self):
        sites = extract_data_sites("SELECT id FROM owners", "sql")
        assert _by(sites, kind="table", name="owners", role="reads")

    def test_bigquery_backtick_triple_id_is_warehouse(self):
        js = "const [rows] = await client.query('SELECT * FROM `clinic.prod.owners`');"
        sites = extract_data_sites(js, "javascript")
        wh = _by(sites, kind="warehouse", system="bigquery")
        assert wh and wh[0].name == "clinic.prod.owners"

    def test_snowflake_import_reroutes_system(self):
        py = ('import snowflake.connector\n'
              'cur.execute("SELECT * FROM owners")\n')
        sites = extract_data_sites(py, "python")
        assert _by(sites, kind="warehouse", name="owners", system="snowflake")


class TestNoSql:
    def test_mongo_collection_and_shell_styles(self):
        js = ("const { MongoClient } = require('mongodb');\n"
              "db.collection('owners').insertOne(doc);\n"
              "db.collection('visits').find({});\n"
              "db.owners.find({ city: 'SF' });\n")
        sites = extract_data_sites(js, "javascript")
        assert _by(sites, kind="collection", name="owners", role="writes")
        assert _by(sites, kind="collection", name="visits", role="reads")
        assert _by(sites, kind="collection", name="owners", role="reads")

    def test_pymongo_subscript_and_attribute(self):
        py = ("import pymongo\n"
              'db["owners"].insert_one(doc)\n'
              "db.visits.find_one({})\n")
        sites = extract_data_sites(py, "python")
        assert _by(sites, name="owners", role="writes", system="mongo")
        assert _by(sites, name="visits", role="reads", system="mongo")

    def test_dynamo_table_case_preserved_and_commands(self):
        sites = extract_data_sites(BOTO3_MODULE, "python")
        assert _by(sites, kind="table", name="owners", role="reads", system="dynamo")
        assert _by(sites, kind="table", name="visits", role="writes", system="dynamo")

        js = ("import { PutItemCommand, QueryCommand } from '@aws-sdk/client-dynamodb';\n"
              "await client.send(new PutItemCommand({ TableName: 'Visits', Item: item }));\n"
              "await client.send(new QueryCommand({ TableName: 'Owners' }));\n")
        js_sites = extract_data_sites(js, "javascript")
        assert _by(js_sites, name="Visits", role="writes", system="dynamo")
        assert _by(js_sites, name="Owners", role="reads", system="dynamo")

    def test_redis_prefix_only_else_nothing(self):
        py = ('import redis\n'
              'r = redis.Redis()\n'
              'cached = redis_client.get("owner:%s" % oid)\n'
              'redis_client.set(key, value)\n')
        sites = extract_data_sites(py, "python")
        cache = _by(sites, kind="cache")
        assert [c.name for c in cache] == ["owner"]
        assert cache[0].system == "redis" and cache[0].attrs == {"prefix": True}


class TestObjectStorage:
    def test_boto3_kwarg_positional_and_env(self):
        sites = extract_data_sites(BOTO3_MODULE, "python")
        assert _by(sites, kind="bucket", name="clinic-reports", role="reads", system="s3")
        assert _by(sites, kind="bucket", name="clinic-media", role="writes")
        env = _by(sites, kind="bucket", dynamic=True)
        assert env and env[0].env_var == "ARCHIVE_BUCKET" and env[0].name == ""

    def test_js_v3_commands_and_gcs(self):
        js = ("import { GetObjectCommand, PutObjectCommand } from '@aws-sdk/client-s3';\n"
              "await s3.send(new GetObjectCommand({ Bucket: 'clinic-reports', Key: k }));\n"
              "await s3.send(new PutObjectCommand({ Bucket: 'clinic-media', Key: k }));\n")
        sites = extract_data_sites(js, "javascript")
        assert _by(sites, name="clinic-reports", role="reads", system="s3")
        assert _by(sites, name="clinic-media", role="writes", system="s3")

        py = ("from google.cloud import storage\n"
              "bucket = client.bucket('clinic-media')\n"
              "bucket.blob(name).upload_from_filename(path)\n")
        gcs = extract_data_sites(py, "python")
        assert _by(gcs, kind="bucket", name="clinic-media", system="gcs")


class TestHygiene:
    def test_per_file_dedupe(self):
        py = ("from elasticsearch import Elasticsearch\n"
              'es.search(index="owners")\nes.search(index="owners")\n')
        sites = extract_data_sites(py, "python")
        assert len(_by(sites, kind="index", name="owners", role="reads")) == 1

    def test_malformed_and_unknown_language_do_not_raise(self):
        assert extract_data_sites("\x00\xff{{{ SELECT FROM", "python") == []
        assert extract_data_sites("SELECT * FROM owners", "cobol") == []
        assert isinstance(extract_data_sites("", None), list)

    def test_every_site_is_a_datasite_with_line(self):
        sites = extract_data_sites(BOTO3_MODULE, "python")
        assert sites and all(isinstance(s, DataSite) and s.line >= 1 for s in sites)
