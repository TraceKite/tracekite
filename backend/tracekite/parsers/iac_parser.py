"""Terraform, Kustomize and ECS parsing.

Terraform is where managed resources — MSK topics, SQS queues, OpenSearch
domains, RDS instances, S3 buckets — actually get their names and ARNs, which is
what M4 and M8 will join against. There is no tree-sitter HCL grammar pinned, so
this is a focused block reader rather than a full HCL implementation: it extracts
block headers and top-level scalar attributes and deliberately stops there.
"""

import json
import logging
import re
from dataclasses import dataclass, field

import yaml
from tracekite.parsers.brace_blocks import balanced_block

logger = logging.getLogger(__name__)

# resource "aws_sqs_queue" "orders" {   /   module "vpc" {   /   output "url" {
_BLOCK = re.compile(
    r'^\s*(resource|data|module|output|variable|locals|provider)'
    r'((?:\s+"[^"]*")*)\s*\{', re.MULTILINE)
_QUOTED = re.compile(r'"([^"]*)"')
# key = "value" | key = 123 | key = true
_ATTR = re.compile(r'^\s*([A-Za-z_][\w.-]*)\s*=\s*(.+?)\s*$', re.MULTILINE)
# ${aws_sqs_queue.orders.url} / aws_sqs_queue.orders.url / var.x / module.y.z
_REFERENCE = re.compile(
    r'\b((?:module|var|local|data)\.[\w.-]+|[a-z][a-z0-9_]*\.[\w.-]+\.[\w-]+)\b')

# Resource types worth surfacing: each is a rendezvous target for M4/M8.
INTERESTING_RESOURCES = {
    # messaging
    "aws_sqs_queue": "queue", "aws_sns_topic": "topic",
    "aws_msk_cluster": "broker", "aws_msk_configuration": "broker",
    "aws_kinesis_stream": "stream", "aws_cloudwatch_event_bus": "eventbus",
    "aws_lambda_event_source_mapping": "event_source",
    "aws_sns_topic_subscription": "subscription",
    "google_pubsub_topic": "topic", "google_pubsub_subscription": "subscription",
    "azurerm_servicebus_queue": "queue", "azurerm_servicebus_topic": "topic",
    "azurerm_eventhub": "stream", "confluent_kafka_topic": "topic",
    # search / data
    "aws_opensearch_domain": "search", "aws_elasticsearch_domain": "search",
    "elasticstack_elasticsearch_index": "index",
    "aws_db_instance": "database", "aws_rds_cluster": "database",
    "aws_dynamodb_table": "database", "aws_elasticache_cluster": "cache",
    "google_sql_database_instance": "database", "azurerm_postgresql_server": "database",
    "aws_s3_bucket": "bucket", "google_storage_bucket": "bucket",
    "snowflake_table": "table", "databricks_sql_table": "table",
    # compute / routing
    "aws_ecs_service": "service", "aws_ecs_task_definition": "task",
    "aws_lambda_function": "function", "aws_api_gateway_rest_api": "gateway",
    "aws_apigatewayv2_api": "gateway", "aws_lb_target_group": "target_group",
    "google_cloud_run_service": "service",
    # gateway wiring
    "aws_apigatewayv2_route": "gw_route",
    "aws_apigatewayv2_integration": "gw_integration",
    "aws_api_gateway_integration": "gw_integration",
    "aws_lb_listener_rule": "lb_rule",
}


@dataclass
class IaCResource:
    """One Terraform block, or one ECS container definition."""
    block_type: str                       # resource | module | output | ...
    resource_type: str = ""               # aws_sqs_queue, ...
    name: str = ""
    category: str = ""                    # queue | topic | search | ...
    attributes: dict = field(default_factory=dict)
    references: list[str] = field(default_factory=list)
    source: str = ""                      # module source
    file_path: str = ""
    line: int = 0

    @property
    def address(self) -> str:
        if self.block_type == "resource":
            return f"{self.resource_type}.{self.name}"
        return f"{self.block_type}.{self.name}" if self.name else self.block_type


def _block_bodies(content: str):
    """Yield (match, body) for each block, brace-balanced.

    An unterminated block yields an empty body rather than swallowing the rest
    of the file: keeping the declaration's identity is useful, but attributing
    every later resource's settings to it would be actively wrong.
    """
    for match in _BLOCK.finditer(content):
        start = content.index("{", match.start())
        # An unterminated block yields no body, which is what balanced_block
        # returns for it — the conservative reading, since a truncated
        # descriptor must contribute nothing rather than swallow the rest of
        # the file.
        body, _end = balanced_block(content, start)
        yield match, body


def _scalar(raw: str) -> str | None:
    raw = raw.strip().rstrip(",")
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return raw[1:-1]
    if raw in ("true", "false") or re.fullmatch(r"-?\d+(\.\d+)?", raw):
        return raw
    return None


def parse_terraform(file_path: str, content: str) -> list[IaCResource]:
    """Extract Terraform blocks."""
    resources: list[IaCResource] = []
    for match, body in _block_bodies(content):
        labels = _QUOTED.findall(match.group(2) or "")
        block_type = match.group(1)
        resource = IaCResource(
            block_type=block_type,
            file_path=file_path,
            line=content.count("\n", 0, match.start()) + 1,
        )
        if block_type in ("resource", "data") and len(labels) >= 2:
            resource.resource_type, resource.name = labels[0], labels[1]
            resource.category = INTERESTING_RESOURCES.get(labels[0], "")
        elif labels:
            resource.name = labels[0]

        for attr in _ATTR.finditer(body):
            key, raw = attr.group(1), attr.group(2)
            if (value := _scalar(raw)) is not None:
                resource.attributes[key] = value
        resource.source = resource.attributes.get("source", "")
        # Only cross-block references matter; a bare `var.x` inside its own
        # block is noise for dependency purposes but kept for output wiring.
        resource.references = sorted(set(_REFERENCE.findall(body)))
        resources.append(resource)
    return resources


def parse_kustomization(file_path: str, content: str) -> list[IaCResource]:
    """Kustomize base/overlay wiring.

    Only the structure is read here: which bases an overlay composes and which
    generators it declares. Rendering patches is out of scope — a wrong render
    is worse than an honest gap.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    if data.get("kind") not in (None, "Kustomization", "Component"):
        return []

    resource = IaCResource(
        block_type="kustomization", name=file_path.rsplit("/", 2)[-2]
        if "/" in file_path else "kustomization",
        file_path=file_path, line=1,
    )
    for key in ("resources", "bases", "components", "patches",
                "patchesStrategicMerge"):
        values = data.get(key)
        if isinstance(values, list):
            resource.references += [str(v) for v in values if isinstance(v, str)]
    resource.attributes["namespace"] = str(data.get("namespace") or "")
    resource.attributes["namePrefix"] = str(data.get("namePrefix") or "")
    resource.attributes["nameSuffix"] = str(data.get("nameSuffix") or "")

    for generator in ("configMapGenerator", "secretGenerator"):
        for entry in data.get(generator) or []:
            if isinstance(entry, dict) and entry.get("name"):
                resource.references.append(f"{generator}:{entry['name']}")

    images = data.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict) and image.get("name"):
                new = image.get("newName") or image["name"]
                resource.attributes[f"image:{image['name']}"] = str(new)
    return [resource]


def parse_ecs_task_definition(file_path: str, content: str) -> list[IaCResource]:
    """ECS task definition JSON: container images and env."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    definitions = data.get("containerDefinitions")
    if not isinstance(definitions, list):
        return []

    family = str(data.get("family") or "")
    resources: list[IaCResource] = []
    for definition in definitions:
        if not isinstance(definition, dict):
            continue
        resource = IaCResource(
            block_type="ecs_container", resource_type="aws_ecs_task_definition",
            name=str(definition.get("name") or family), category="task",
            file_path=file_path, line=1,
        )
        resource.attributes["family"] = family
        resource.attributes["image"] = str(definition.get("image") or "")
        for entry in definition.get("environment") or []:
            if isinstance(entry, dict) and entry.get("name"):
                resource.attributes[f"env:{entry['name']}"] = str(
                    entry.get("value") or "")
        for entry in definition.get("secrets") or []:
            if isinstance(entry, dict) and entry.get("name"):
                # Name only — the valueFrom ARN may embed a secret path.
                resource.attributes[f"secret:{entry['name']}"] = ""
        resources.append(resource)
    return resources


def is_terraform_file(file_name: str) -> bool:
    return file_name.endswith((".tf", ".tf.json", ".tfvars"))


def is_kustomization_file(file_name: str) -> bool:
    return file_name in ("kustomization.yaml", "kustomization.yml")


def parse_iac_file(file_path: str, content: str) -> list[IaCResource]:
    file_name = file_path.rsplit("/", 1)[-1]
    if is_terraform_file(file_name):
        return parse_terraform(file_path, content)
    if is_kustomization_file(file_name):
        return parse_kustomization(file_path, content)
    if file_name.endswith(".json") and "containerDefinitions" in content:
        return parse_ecs_task_definition(file_path, content)
    return []
