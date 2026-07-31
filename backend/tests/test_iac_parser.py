"""Terraform / Kustomize / ECS parsing."""

import pytest

from adduce.parsers.iac_parser import (
    parse_ecs_task_definition, parse_iac_file, parse_kustomization,
    parse_terraform,
)
from adduce.parsers.parser_registry import is_iac_file

TERRAFORM = '''
terraform {
  required_version = ">= 1.5"
}

resource "aws_sqs_queue" "orders_events" {
  name                       = "orders-events"
  visibility_timeout_seconds = 30
  fifo_queue                 = false
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.orders_dlq.arn
  })
}

resource "aws_sqs_queue" "orders_dlq" {
  name = "orders-events-dlq"
}

resource "aws_opensearch_domain" "search" {
  domain_name    = "product-search"
  engine_version = "OpenSearch_2.11"
}

resource "aws_msk_cluster" "events" {
  cluster_name = "platform-events"
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.0.0"
  name    = "platform-vpc"
}

output "queue_url" {
  value = aws_sqs_queue.orders_events.url
}
'''


class TestTerraform:
    def test_resource_blocks_and_addresses(self):
        resources = parse_terraform("infra/main.tf", TERRAFORM)
        addresses = {r.address for r in resources}
        assert "aws_sqs_queue.orders_events" in addresses
        assert "aws_opensearch_domain.search" in addresses
        assert "module.vpc" in addresses

    def test_categories_classify_managed_resources(self):
        by_address = {r.address: r for r in parse_terraform("m.tf", TERRAFORM)}
        assert by_address["aws_sqs_queue.orders_events"].category == "queue"
        assert by_address["aws_opensearch_domain.search"].category == "search"
        assert by_address["aws_msk_cluster.events"].category == "broker"

    def test_scalar_attributes_extracted(self):
        by_address = {r.address: r for r in parse_terraform("m.tf", TERRAFORM)}
        queue = by_address["aws_sqs_queue.orders_events"]
        assert queue.attributes["name"] == "orders-events"
        assert queue.attributes["visibility_timeout_seconds"] == "30"
        assert queue.attributes["fifo_queue"] == "false"

    def test_module_source_captured(self):
        by_address = {r.address: r for r in parse_terraform("m.tf", TERRAFORM)}
        assert by_address["module.vpc"].source == "terraform-aws-modules/vpc/aws"

    def test_cross_resource_references_recorded(self):
        by_address = {r.address: r for r in parse_terraform("m.tf", TERRAFORM)}
        # The DLQ wiring is only visible as a reference, not a scalar.
        assert any("aws_sqs_queue.orders_dlq" in ref
                   for ref in by_address["aws_sqs_queue.orders_events"].references)

    def test_output_wiring_is_a_cross_repo_join_key(self):
        by_address = {r.address: r for r in parse_terraform("m.tf", TERRAFORM)}
        output = by_address["output.queue_url"]
        assert output.block_type == "output"
        assert any("aws_sqs_queue.orders_events" in r for r in output.references)

    def test_nested_braces_do_not_truncate_a_block(self):
        resources = parse_terraform("m.tf", TERRAFORM)
        # jsonencode({...}) inside the queue must not end the block early, so
        # the following resource is still found.
        assert any(r.address == "aws_sqs_queue.orders_dlq" for r in resources)

    def test_malformed_hcl_does_not_raise(self):
        assert parse_terraform("empty.tf", "") == []
        # An unterminated block keeps its identity but contributes no
        # attributes — swallowing the rest of the file would attribute later
        # resources' settings to it.
        [res] = parse_terraform("bad.tf", 'resource "x" "y" {\n  name = "n"\n')
        assert res.address == "x.y"
        assert res.attributes == {}

    def test_unterminated_block_does_not_capture_later_resources(self):
        resources = parse_terraform("bad.tf", '''
resource "aws_sqs_queue" "broken" {
  name = "broken"

resource "aws_sqs_queue" "later" {
  name = "later-queue"
}
''')
        by_address = {r.address: r for r in resources}
        assert by_address["aws_sqs_queue.later"].attributes["name"] == "later-queue"
        assert "name" not in by_address["aws_sqs_queue.broken"].attributes


class TestKustomize:
    def test_overlay_bases_and_namespace(self):
        [res] = parse_kustomization("deploy/overlays/prod/kustomization.yaml", """
namespace: prod
namePrefix: prod-
resources:
  - ../../base
  - extra-service.yaml
images:
  - name: myorg/orders
    newName: registry.internal/myorg/orders
""")
        assert res.attributes["namespace"] == "prod"
        assert res.attributes["namePrefix"] == "prod-"
        assert "../../base" in res.references
        assert res.attributes["image:myorg/orders"] == \
            "registry.internal/myorg/orders"

    def test_generators_recorded(self):
        [res] = parse_kustomization("k/kustomization.yaml", """
configMapGenerator:
  - name: app-config
secretGenerator:
  - name: app-secrets
""")
        assert "configMapGenerator:app-config" in res.references
        assert "secretGenerator:app-secrets" in res.references

    def test_non_kustomization_yaml_ignored(self):
        assert parse_kustomization("k/kustomization.yaml",
                                   "kind: Deployment\n") == []

    def test_malformed_yaml_does_not_raise(self):
        assert parse_kustomization("k/kustomization.yaml", "bad: [") == []


ECS_TASK = """
{
  "family": "orders-task",
  "containerDefinitions": [
    {
      "name": "orders",
      "image": "registry.internal/myorg/orders:1.2.3",
      "environment": [
        {"name": "VETS_URL", "value": "http://vets.internal:8080"},
        {"name": "LOG_LEVEL", "value": "info"}
      ],
      "secrets": [
        {"name": "DB_PASSWORD", "valueFrom": "arn:aws:secretsmanager:...:pw"}
      ]
    }
  ]
}
"""


class TestEcs:
    def test_container_image_and_family(self):
        [res] = parse_ecs_task_definition("ecs/orders.json", ECS_TASK)
        assert res.name == "orders"
        assert res.attributes["family"] == "orders-task"
        assert res.attributes["image"] == "registry.internal/myorg/orders:1.2.3"

    def test_environment_extracted(self):
        [res] = parse_ecs_task_definition("ecs/orders.json", ECS_TASK)
        assert res.attributes["env:VETS_URL"] == "http://vets.internal:8080"
        assert res.attributes["env:LOG_LEVEL"] == "info"

    def test_secret_arns_are_not_stored(self):
        # A valueFrom ARN can embed a secret path; only the name is kept.
        [res] = parse_ecs_task_definition("ecs/orders.json", ECS_TASK)
        assert res.attributes["secret:DB_PASSWORD"] == ""
        assert not any("secretsmanager" in str(v)
                       for v in res.attributes.values())

    def test_malformed_json_does_not_raise(self):
        assert parse_ecs_task_definition("t.json", "{bad") == []
        assert parse_ecs_task_definition("t.json", '{"family": "x"}') == []


class TestDispatch:
    @pytest.mark.parametrize("name,expected", [
        ("main.tf", True), ("vars.tfvars", True),
        ("kustomization.yaml", True), ("kustomization.yml", True),
        ("deployment.yaml", False), ("app.py", False),
    ])
    def test_is_iac_file_by_name(self, name, expected):
        assert is_iac_file(name, "") is expected

    def test_ecs_json_detected_by_content(self):
        assert is_iac_file("task.json", '{"containerDefinitions": []}') is True
        assert is_iac_file("package.json", '{"name": "x"}') is False

    def test_parse_iac_file_routes_correctly(self):
        assert parse_iac_file("main.tf", TERRAFORM)
        assert parse_iac_file("kustomization.yaml", "namespace: prod\n")
        assert parse_iac_file("task.json", ECS_TASK)
        assert parse_iac_file("random.txt", "hello") == []
