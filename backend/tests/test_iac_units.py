"""Each IaC format produces claims.

Four syntaxes, one meaning: a unit exists, it runs something, its
environment points at other services. The tests pin each format through
the real scan — and each format's decline, because the formats' file
shapes collide with ordinary configuration everywhere.
"""

from tracekite import engine_config
from tracekite.db.memory_store import claims_from_scan
from tracekite.parsers.iac_units import (
    extract_iac_services, parse_ansible, parse_nomad, parse_systemd,
)
from tracekite.services.scan import scan


def scanned_claims(tmp_path, relpath, content):
    engine_config.configure(graph_hmac_key="iac-units-test")
    target = tmp_path / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return claims_from_scan(scan(str(tmp_path), "iac_repo"))


class TestNomad:
    JOB = '''
job "billing" {
  group "app" {
    task "server" {
      driver = "docker"
      config { image = "registry.internal/org/billing:1" }
      env {
        ORDERS_URL = "http://orders-service:8080"
      }
      service { name = "billing-service" port = "http" }
    }
  }
}
'''

    def test_a_job_claims_identity_and_env_host(self, tmp_path):
        claims = scanned_claims(tmp_path, "deploy/billing.nomad", self.JOB)
        provides = [c for c in claims if c.direction == "provides"
                    and c.kind == "svcname"]
        assert [c.service_hint for c in provides] == ["billing-service"]
        consumes = [c for c in claims if c.attrs.get("via") == "env_host"]
        assert [c.service_hint for c in consumes] == ["orders-service"]

    def test_an_hcl_file_that_is_not_nomad_is_declined(self):
        assert parse_nomad("main.tf", self.JOB) == []


class TestSystemd:
    UNIT = ("[Unit]\nDescription=Billing\n\n[Service]\n"
            'Environment="ORDERS_URL=http://orders-service:8080" '
            '"LOG_LEVEL=info"\n'
            "ExecStart=/usr/bin/billing\n")

    def test_a_unit_file_claims_by_filename(self, tmp_path):
        claims = scanned_claims(
            tmp_path, "deploy/billing-service.service", self.UNIT)
        provides = [c for c in claims if c.direction == "provides"
                    and c.kind == "svcname"]
        assert [c.service_hint for c in provides] == ["billing-service"]
        consumes = [c for c in claims if c.attrs.get("via") == "env_host"]
        assert [c.service_hint for c in consumes] == ["orders-service"]

    def test_a_dot_service_file_without_the_section_is_not_a_unit(self):
        assert parse_systemd("api.service", "just some text\n") == []


class TestAnsible:
    PLAYBOOK = '''
- hosts: app_servers
  tasks:
    - name: run billing
      docker_container:
        name: billing-service
        image: registry.internal/org/billing:1
        env:
          ORDERS_URL: http://orders-service:8080
'''

    def test_a_docker_container_task_claims(self, tmp_path):
        claims = scanned_claims(tmp_path, "deploy/site.yml", self.PLAYBOOK)
        assert [c.service_hint for c in claims
                if c.direction == "provides" and c.kind == "svcname"] \
            == ["billing-service"]

    def test_a_templated_name_is_declined_not_rendered(self):
        """Quoted, because unquoted {{ }} is invalid YAML and the parser
        declines it before the guard is even asked — the guard exists for
        the form that parses."""
        templated = self.PLAYBOOK.replace('name: billing-service',
                                          'name: "{{ service_name }}"')
        assert parse_ansible("site.yml", templated) == []

    def test_ordinary_yaml_is_not_a_playbook(self):
        assert parse_ansible("config.yml", "retries: 3\ntimeout: 5\n") == []


class TestPulumi:
    PROGRAM = '''
import * as awsx from "@pulumi/awsx";

const service = new awsx.ecs.FargateService("billing-service", {
    taskDefinitionArgs: {
        container: {
            environment: {
                ORDERS_URL: "http://orders-service:8080",
            },
        },
    },
});
'''

    def test_a_service_constructor_claims(self):
        [unit] = extract_iac_services("infra/index.ts", self.PROGRAM,
                                      "typescript")
        assert unit.name == "billing-service"
        assert unit.env == {"ORDERS_URL": "http://orders-service:8080"}

    def test_a_constructed_name_is_not_extracted(self):
        program = self.PROGRAM.replace('"billing-service"', "serviceName")
        assert extract_iac_services("infra/index.ts", program,
                                    "typescript") == []
