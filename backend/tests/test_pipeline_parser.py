"""Data & ML pipeline parsing."""

from evigraph.parsers.pipeline_parser import (
    extract_spark_datasets, is_pipeline_file, parse_airflow_dag,
    parse_databricks_bundle, parse_databricks_notebook, parse_dbt_model,
    parse_dbt_project, parse_dbt_sources,
)


def _by_role(source, role):
    datasets = source if isinstance(source, list) else source.datasets
    return {d.name: d for d in datasets if d.role == role}


# --------------------------------------------------------------------------
# dbt
# --------------------------------------------------------------------------

DBT_PROJECT = """
name: jaffle_shop
version: "1.0.0"
profile: warehouse_prod
model-paths: ["models"]
models:
  jaffle_shop:
    +materialized: view
"""

DBT_MODEL = """\
{{ config(materialized='incremental') }}

with orders as (
    select * from {{ ref('stg_orders') }}
),
payments as (
    select * from {{ ref('stg_payments') }}
),
customers as (
    select * from {{ source('jaffle_shop', 'customers') }}
)
select o.order_id, p.amount
from orders o
join payments p on o.order_id = p.order_id
"""

DBT_SCHEMA = """\
version: 2

sources:
  - name: jaffle_shop
    schema: raw
    tables:
      - name: orders
        identifier: raw_orders_v2
      - name: customers

  - name: stripe
    tables:
      - name: payments

models:
  - name: fct_orders
    description: One row per order
  - name: dim_customers
"""


class TestDbtProject:
    def test_project_identity(self):
        info = parse_dbt_project("dbt_project.yml", DBT_PROJECT)
        assert info.framework == "dbt"
        assert info.name == "jaffle_shop"
        assert info.attrs["profile"] == "warehouse_prod"
        assert info.datasets == []          # a project file declares nothing

    def test_malformed_returns_none(self):
        assert parse_dbt_project("dbt_project.yml", "name: [unclosed") is None
        assert parse_dbt_project("dbt_project.yml", "- just\n- a list\n") is None


class TestDbtModel:
    def test_model_writes_its_own_name(self):
        info = parse_dbt_model("models/marts/fct_orders.sql", DBT_MODEL)
        assert info.framework == "dbt"
        assert info.name == "fct_orders"
        assert _by_role(info, "writes")["fct_orders"].kind == "model"

    def test_refs_become_model_reads(self):
        reads = _by_role(parse_dbt_model("models/m.sql", DBT_MODEL), "reads")
        assert reads["stg_orders"].kind == "model"
        assert "stg_payments" in reads

    def test_source_becomes_qualified_table_read(self):
        reads = _by_role(parse_dbt_model("models/m.sql", DBT_MODEL), "reads")
        assert reads["jaffle_shop.customers"].kind == "table"
        assert reads["jaffle_shop.customers"].attrs["source"] == "jaffle_shop"

    def test_raw_from_clauses_are_not_guessed(self):
        # `from orders o` names a CTE — only ref()/source() are lineage.
        names = {d.name for d in parse_dbt_model("models/m.sql", DBT_MODEL).datasets}
        assert "orders" not in names and "payments" not in names

    def test_materialized_config_captured(self):
        info = parse_dbt_model("models/m.sql", DBT_MODEL)
        assert info.attrs["materialized"] == "incremental"

    def test_two_arg_ref_records_package(self):
        info = parse_dbt_model(
            "models/a.sql", "select * from {{ ref('core', 'dim_dates') }}")
        assert _by_role(info, "reads")["dim_dates"].attrs["package"] == "core"

    def test_dynamic_ref_flagged_never_guessed(self):
        info = parse_dbt_model(
            "models/a.sql", "select * from {{ ref(var('which_model')) }}")
        assert _by_role(info, "reads") == {}
        assert info.attrs.get("dynamic") is True


class TestDbtSchema:
    def test_source_tables_declared_with_schema(self):
        declares = _by_role(
            parse_dbt_sources("models/staging/schema.yml", DBT_SCHEMA), "declares")
        assert declares["raw.orders"].kind == "table"
        assert declares["raw.orders"].attrs["identifier"] == "raw_orders_v2"
        assert declares["raw.orders"].attrs["source"] == "jaffle_shop"
        assert "raw.customers" in declares

    def test_schema_falls_back_to_source_name(self):
        declares = _by_role(
            parse_dbt_sources("models/schema.yml", DBT_SCHEMA), "declares")
        assert "stripe.payments" in declares

    def test_models_declared(self):
        declares = _by_role(
            parse_dbt_sources("models/schema.yml", DBT_SCHEMA), "declares")
        assert declares["fct_orders"].kind == "model"
        assert "dim_customers" in declares

    def test_nothing_declared_returns_none(self):
        assert parse_dbt_sources("models/x.yml", "version: 2\n") is None
        assert parse_dbt_sources("models/x.yml", ": bad [yaml") is None


# --------------------------------------------------------------------------
# Airflow
# --------------------------------------------------------------------------

AIRFLOW_DAG = '''
from datetime import datetime
from airflow import DAG
from airflow.providers.postgres.operators.postgres import PostgresOperator
from airflow.providers.amazon.aws.transfers.s3_to_redshift import S3ToRedshiftOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.sensors.external_task import ExternalTaskSensor

with DAG("orders_etl", schedule="@daily", start_date=datetime(2024, 1, 1)) as dag:
    wait_upstream = ExternalTaskSensor(
        task_id="wait_for_ingest",
        external_dag_id="raw_ingest",
        external_task_id="done",
    )

    load_stage = S3ToRedshiftOperator(
        task_id="load_stage",
        s3_bucket="data-lake-prod",
        s3_key="exports/orders/{{ ds }}/part.parquet",
        schema="staging",
        table="stg_orders",
    )

    aggregate = PostgresOperator(
        task_id="aggregate",
        postgres_conn_id="dwh",
        sql="""
            insert into analytics.daily_orders
            select order_date, count(*) as n
            from staging.stg_orders
            where order_date = '{{ ds }}'
            group by order_date
        """,
    )

    kick_downstream = TriggerDagRunOperator(
        task_id="kick_reporting",
        trigger_dag_id="reporting_refresh",
    )
'''

TASKFLOW_DAG = '''
import pendulum
from airflow.decorators import dag, task

@dag(schedule=None, start_date=pendulum.datetime(2024, 1, 1), catchup=False)
def nightly_metrics():
    @task
    def compute():
        return 1
    compute()

nightly_metrics()
'''


class TestAirflow:
    def test_dag_identity(self):
        info = parse_airflow_dag("dags/orders_etl.py", AIRFLOW_DAG)
        assert info.framework == "airflow"
        assert info.name == "orders_etl"
        assert info.attrs["schedule"] == "@daily"

    def test_cross_dag_dependencies(self):
        info = parse_airflow_dag("dags/orders_etl.py", AIRFLOW_DAG)
        assert "raw_ingest" in info.depends_on          # ExternalTaskSensor
        assert "reporting_refresh" in info.depends_on   # TriggerDagRunOperator

    def test_sql_operator_tables(self):
        info = parse_airflow_dag("dags/orders_etl.py", AIRFLOW_DAG)
        writes = _by_role(info, "writes")
        reads = _by_role(info, "reads")
        assert "analytics.daily_orders" in writes
        assert reads["staging.stg_orders"].kind == "table"

    def test_templated_sql_flagged_but_literals_kept(self):
        info = parse_airflow_dag("dags/orders_etl.py", AIRFLOW_DAG)
        writes = _by_role(info, "writes")
        assert writes["analytics.daily_orders"].attrs.get("templated") is True
        # the '{{ ds }}' hole itself never became a dataset name
        assert all("{{" not in d.name for d in info.datasets)

    def test_s3_to_redshift_copy(self):
        info = parse_airflow_dag("dags/orders_etl.py", AIRFLOW_DAG)
        bucket = _by_role(info, "reads")["data-lake-prod"]
        assert bucket.kind == "dataset"
        assert bucket.attrs["path"].startswith("s3://data-lake-prod/exports/")
        assert "staging.stg_orders" in _by_role(info, "writes")

    def test_dag_id_kwarg(self):
        info = parse_airflow_dag(
            "d.py", 'from airflow import DAG\nd = DAG(dag_id="nightly")\n')
        assert info.name == "nightly"

    def test_taskflow_decorator_uses_function_name(self):
        info = parse_airflow_dag("dags/metrics.py", TASKFLOW_DAG)
        assert info.name == "nightly_metrics"

    def test_delete_from_is_a_write(self):
        info = parse_airflow_dag("d.py", (
            "from airflow import DAG\n"
            "from airflow.providers.postgres.operators.postgres import PostgresOperator\n"
            'with DAG("cleanup") as dag:\n'
            '    purge = PostgresOperator(task_id="p", sql="delete from staging.tmp_orders")\n'))
        assert "staging.tmp_orders" in _by_role(info, "writes")
        assert _by_role(info, "reads") == {}

    def test_dynamic_trigger_id_flagged_not_guessed(self):
        info = parse_airflow_dag("d.py", (
            "from airflow import DAG\n"
            "from airflow.operators.trigger_dagrun import TriggerDagRunOperator\n"
            'with DAG("fanout") as dag:\n'
            '    t = TriggerDagRunOperator(task_id="t", trigger_dag_id=f"report_{region}")\n'))
        assert info.depends_on == []
        assert info.attrs.get("dynamic") is True

    def test_not_a_dag_returns_none(self):
        assert parse_airflow_dag("x.py", "import pandas as pd\n") is None
        assert parse_airflow_dag("x.py", "from airflow import DAG\n") is None


# --------------------------------------------------------------------------
# Databricks
# --------------------------------------------------------------------------

DATABRICKS_BUNDLE = """\
bundle:
  name: churn-pipeline

resources:
  jobs:
    nightly_scoring:
      name: nightly-scoring
      job_clusters:
        - job_cluster_key: main
          new_cluster:
            spark_version: 15.4.x-scala2.12
            num_workers: 4
            spark_env_vars:
              DB_PASSWORD: "{{secrets/prod-kv/db-password}}"
      tasks:
        - task_key: featurize
          notebook_task:
            notebook_path: ./notebooks/featurize.py
          job_cluster_key: main
        - task_key: score
          notebook_task:
            notebook_path: /Workspace/Shared/score_model
          depends_on:
            - task_key: featurize
        - task_key: publish
          spark_python_task:
            python_file: ./jobs/publish_scores.py

  pipelines:
    bronze_ingest:
      name: bronze-ingest
      libraries:
        - notebook:
            path: ./dlt/bronze_orders.py
      configuration:
        api_token: "{{secrets/prod-kv/service-api-token}}"
"""

DATABRICKS_NOTEBOOK = '''# Databricks notebook source
# MAGIC %md
# MAGIC Featurization notebook

# COMMAND ----------

# MAGIC %run /Workspace/Shared/common_utils

# COMMAND ----------

%run ../lib/feature_helpers

# COMMAND ----------

import json

api_key = dbutils.secrets.get(scope="ml-scope", key="feature-api-key")
fallback_password = "sup3r-s3cret-value"

orders = spark.table("prod.silver.orders")
customers = spark.read.table("silver.customers")

features = orders.join(customers, "customer_id")
features.write.mode("overwrite").saveAsTable("prod.gold.churn_features")

spark.sql("""
    insert into prod.gold.feature_audit
    select current_timestamp() as run_at, count(*) as n from prod.gold.churn_features
""")

result = dbutils.notebook.run("./score_batch", 3600, {"date": "2026-07-01"})
'''

DLT_NOTEBOOK = '''# Databricks notebook source
import dlt
from pyspark.sql import functions as F

@dlt.table(comment="Bronze orders")
def bronze_orders():
    return spark.readStream.format("cloudFiles").load("/mnt/landing/orders")

@dlt.table(name="silver_orders")
def build_silver():
    return dlt.read("bronze_orders").where(F.col("amount") > 0)
'''


class TestDatabricksBundle:
    def test_bundle_identity_and_resources(self):
        info = parse_databricks_bundle("databricks.yml", DATABRICKS_BUNDLE)
        assert info.framework == "databricks"
        assert info.name == "churn-pipeline"
        assert info.attrs["jobs"] == ["nightly_scoring"]
        assert info.attrs["pipelines"] == ["bronze_ingest"]

    def test_task_notebooks_and_dlt_libraries_are_dependencies(self):
        info = parse_databricks_bundle("databricks.yml", DATABRICKS_BUNDLE)
        assert set(info.depends_on) == {
            "./notebooks/featurize.py", "/Workspace/Shared/score_model",
            "./jobs/publish_scores.py", "./dlt/bronze_orders.py"}

    def test_secret_scopes_names_only_never_keys_or_values(self):
        info = parse_databricks_bundle("databricks.yml", DATABRICKS_BUNDLE)
        assert info.attrs["secret_scopes"] == ["prod-kv"]
        assert "db-password" not in repr(info)
        assert "service-api-token" not in repr(info)

    def test_not_a_bundle_returns_none(self):
        assert parse_databricks_bundle(
            "databricks.yml", "kind: Service\nmetadata:\n  name: x\n") is None
        assert parse_databricks_bundle("databricks.yml", "{{ not yaml") is None


class TestDatabricksNotebook:
    def test_header_is_required(self):
        assert parse_databricks_notebook(
            "etl.py", 'import pyspark\nspark.table("a.b")\n') is None

    def test_identity(self):
        info = parse_databricks_notebook(
            "notebooks/featurize.py", DATABRICKS_NOTEBOOK)
        assert info.framework == "databricks"
        assert info.name == "featurize"

    def test_run_chain_dependencies(self):
        info = parse_databricks_notebook(
            "notebooks/featurize.py", DATABRICKS_NOTEBOOK)
        assert info.depends_on == [
            "/Workspace/Shared/common_utils",   # `# MAGIC %run`
            "../lib/feature_helpers",           # bare `%run`
            "./score_batch",                    # dbutils.notebook.run
        ]

    def test_unity_catalog_three_part_names_are_warehouse_kind(self):
        reads = _by_role(parse_databricks_notebook(
            "notebooks/featurize.py", DATABRICKS_NOTEBOOK), "reads")
        assert reads["prod.silver.orders"].kind == "warehouse"
        assert reads["silver.customers"].kind == "table"

    def test_line_numbers_survive_comment_stripping(self):
        # Blank-line + comment sequences must not shift later line numbers.
        info = parse_databricks_notebook(
            "notebooks/featurize.py", DATABRICKS_NOTEBOOK)
        lines = {(d.name, d.role): d.line for d in info.datasets}
        assert lines[("prod.silver.orders", "reads")] == 20
        assert lines[("prod.gold.feature_audit", "writes")] == 27

    def test_save_as_table_write(self):
        writes = _by_role(parse_databricks_notebook(
            "notebooks/featurize.py", DATABRICKS_NOTEBOOK), "writes")
        assert writes["prod.gold.churn_features"].kind == "warehouse"

    def test_spark_sql_reads_and_writes(self):
        info = parse_databricks_notebook(
            "notebooks/featurize.py", DATABRICKS_NOTEBOOK)
        assert "prod.gold.feature_audit" in _by_role(info, "writes")
        assert "prod.gold.churn_features" in _by_role(info, "reads")

    def test_secret_refs_names_only_never_values(self):
        info = parse_databricks_notebook(
            "notebooks/featurize.py", DATABRICKS_NOTEBOOK)
        assert info.attrs["secret_refs"] == ["ml-scope/feature-api-key"]
        assert "sup3r-s3cret-value" not in repr(info)

    def test_dlt_notebook(self):
        info = parse_databricks_notebook("dlt/bronze_orders.py", DLT_NOTEBOOK)
        writes = _by_role(info, "writes")
        reads = _by_role(info, "reads")
        assert info.framework == "dlt"
        assert writes["bronze_orders"].attrs.get("dlt") is True   # def name
        assert "silver_orders" in writes                          # name= kwarg
        assert reads["bronze_orders"].attrs.get("dlt") is True    # dlt.read()
        assert reads["/mnt/landing/orders"].attrs["format"] == "cloudFiles"


# --------------------------------------------------------------------------
# Generic Spark + MLflow
# --------------------------------------------------------------------------

SPARK_JOB = '''
from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("orders-gold").getOrCreate()

raw = spark.read.parquet("s3://data-lake-prod/bronze/orders/")

events = (
    spark.readStream
    .format("kafka")
    .option("kafka.bootstrap.servers", "broker:9092")
    .option("subscribe", "orders.created,orders.cancelled")
    .load()
)

dim = spark.read.format("delta").load("/mnt/warehouse/dim_customers")

joined = raw.join(dim, "customer_id")

joined.write.mode("overwrite").insertInto("gold.orders_wide")

joined.write.format("delta").saveAsTable("prod.gold.orders_daily")

out = joined.selectExpr("to_json(struct(*)) AS value")

(out.writeStream
    .format("kafka")
    .option("kafka.bootstrap.servers", "broker:9092")
    .option("topic", "orders.enriched")
    .start())

table_name = compute_table_name()
frame = spark.table(table_name)
also = spark.table(f"{catalog}.events")

import mlflow
import mlflow.sklearn

mlflow.sklearn.log_model(model, "model", registered_model_name="churn-classifier")
mlflow.register_model("runs:/abc123/model", "orders-forecaster")
'''

SCALA_JOB = '''
val df = spark.read.table("hive.default.events")

df.write.mode("overwrite").parquet("gs://analytics-lake/events/")

// spark.read.parquet("gs://commented-out/nope")
'''


class TestSparkGeneric:
    def test_object_store_reads_named_by_bucket(self):
        reads = _by_role(extract_spark_datasets(SPARK_JOB, "python"), "reads")
        assert reads["data-lake-prod"].kind == "dataset"
        assert reads["data-lake-prod"].attrs["path"] == "s3://data-lake-prod/bronze/orders/"
        assert reads["data-lake-prod"].attrs["format"] == "parquet"

    def test_format_load_path_read(self):
        reads = _by_role(extract_spark_datasets(SPARK_JOB, "python"), "reads")
        assert reads["/mnt/warehouse/dim_customers"].attrs["format"] == "delta"

    def test_table_writes(self):
        writes = _by_role(extract_spark_datasets(SPARK_JOB, "python"), "writes")
        assert writes["gold.orders_wide"].kind == "table"
        assert writes["prod.gold.orders_daily"].kind == "warehouse"

    def test_kafka_topics_captured_for_messaging_join(self):
        datasets = extract_spark_datasets(SPARK_JOB, "python")
        reads = _by_role(datasets, "reads")
        writes = _by_role(datasets, "writes")
        assert reads["orders.created"].attrs["kafka_topic"] == "orders.created"
        assert "orders.cancelled" in reads
        assert writes["orders.enriched"].attrs["kafka_topic"] == "orders.enriched"

    def test_dynamic_arguments_never_guessed(self):
        names = {d.name for d in extract_spark_datasets(SPARK_JOB, "python")}
        assert "table_name" not in names
        assert all("{" not in name for name in names)

    def test_mlflow_models_declared(self):
        declares = _by_role(extract_spark_datasets(SPARK_JOB, "python"), "declares")
        assert declares["churn-classifier"].attrs == {"mlflow_model": True}
        assert declares["churn-classifier"].kind == "dataset"
        assert "orders-forecaster" in declares

    def test_scala_source_and_comment_stripping(self):
        datasets = extract_spark_datasets(SCALA_JOB, "scala")
        assert _by_role(datasets, "reads")["hive.default.events"].kind == "warehouse"
        assert "analytics-lake" in _by_role(datasets, "writes")
        assert all("commented-out" not in d.name for d in datasets)

    def test_jdbc_dbtable_option(self):
        content = ('df = spark.read.format("jdbc")'
                   '.option("dbtable", "public.users").option("url", cfg).load()\n')
        assert _by_role(extract_spark_datasets(content, "python"),
                        "reads")["public.users"].kind == "table"

    def test_empty_and_plain_source(self):
        assert extract_spark_datasets("", None) == []
        assert extract_spark_datasets("x = 1\n", "python") == []


# --------------------------------------------------------------------------
# Classification + robustness
# --------------------------------------------------------------------------

class TestIsPipelineFile:
    def test_dbt_classifications(self):
        assert is_pipeline_file("dbt_project.yml", DBT_PROJECT) == "dbt-project"
        assert is_pipeline_file("models/marts/fct_orders.sql", "select 1") == "dbt-model"
        assert is_pipeline_file(
            "analyses/adhoc.sql", "select * from {{ ref('m') }}") == "dbt-model"
        assert is_pipeline_file("models/staging/schema.yml", DBT_SCHEMA) == "dbt-schema"

    def test_databricks_classifications(self):
        assert is_pipeline_file("infra/databricks.yml", DATABRICKS_BUNDLE) == "databricks-bundle"
        assert is_pipeline_file("notebooks/etl.py", DATABRICKS_NOTEBOOK) == "databricks-notebook"

    def test_airflow_classification(self):
        assert is_pipeline_file("dags/orders_etl.py", AIRFLOW_DAG) == "airflow"

    def test_non_pipeline_files_stay_unclassified(self):
        assert is_pipeline_file("scripts/util.py", "import os\n") == ""
        assert is_pipeline_file("queries/report.sql", "select 1") == ""
        assert is_pipeline_file(
            "deploy/app.yaml", "kind: Service\nmetadata:\n  name: x\n") == ""


class TestNeverRaises:
    JUNK = "\x00 {{ ]] : %run @dag DAG( ::"

    def test_garbage_input_returns_none_everywhere(self):
        parsers = (parse_dbt_project, parse_dbt_model, parse_dbt_sources,
                   parse_airflow_dag, parse_databricks_bundle,
                   parse_databricks_notebook)
        for parser in parsers:
            assert parser("junk.file", self.JUNK) is None
            assert parser("junk.file", "") is None

    def test_extract_tolerates_junk(self):
        assert extract_spark_datasets(self.JUNK, "python") == []
        assert is_pipeline_file("junk.file", self.JUNK) == ""

    def test_unterminated_dag_call_keeps_identity_only(self):
        info = parse_airflow_dag(
            "d.py", 'from airflow import DAG\ndag = DAG("orders"')
        assert info is not None
        assert info.name == ""                      # never guess a truncated id
        assert info.attrs.get("dynamic") is True
