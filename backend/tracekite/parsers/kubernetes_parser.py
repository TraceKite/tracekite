"""Kubernetes manifest parsing (design §3.2).

The previous version read only `metadata` and dropped the entire `spec`, which
is where every cross-repo signal lives: container images, the env bindings that
carry Kafka brokers / queue URLs / service URLs, Service selectors, and Ingress
backends. Secret *values* are still never read — only key names — so a manifest
can never move a credential into the graph.
"""

import logging
import re
from dataclasses import dataclass, field

import yaml
from tracekite.parsers.yaml_shapes import as_list as _as_list, as_str as _str

logger = logging.getLogger(__name__)

# Traefik rule expressions: Host(`shop.example.com`) && PathPrefix(`/api`)
_TRAEFIK_HOST = re.compile(r"Host\(\s*`([^`]+)`")
_TRAEFIK_PATH = re.compile(r"(PathPrefix|Path)\(\s*`([^`]+)`")

WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob",
                  "ReplicaSet", "Pod", "Rollout"}

K8S_KINDS = WORKLOAD_KINDS | {
    "Service", "ConfigMap", "Secret", "Ingress", "PersistentVolumeClaim",
    "PersistentVolume", "Namespace", "Role", "RoleBinding", "ClusterRole",
    "ClusterRoleBinding", "ServiceAccount", "HorizontalPodAutoscaler",
    "NetworkPolicy", "AuthorizationPolicy", "ScaledObject", "ScaledJob",
    "Gateway", "HTTPRoute",
    "GRPCRoute", "VirtualService", "DestinationRule", "ServiceEntry",
    "Application", "ApplicationSet", "Kustomization", "HelmRelease",
    "IngressRoute", "Middleware",
}

# Conventional labels that name the service a workload belongs to.
NAME_LABELS = ("app.kubernetes.io/name", "app.kubernetes.io/instance",
               "app.kubernetes.io/component", "app", "k8s-app",
               "tags.datadoghq.com/service")
PART_OF_LABEL = "app.kubernetes.io/part-of"


@dataclass
class EnvBinding:
    """One environment variable a container receives.

    ``source`` is the whole point of the class: ``literal`` is joinable
    immediately, while ``configmap``/``secret`` need the R9 indirection pass to
    resolve against the object they reference.
    """
    name: str
    source: str                   # literal | configmap | secret | field | resource
    value: str | None = None      # literal only; redacted downstream
    ref_name: str | None = None   # ConfigMap/Secret object name
    ref_key: str | None = None    # key within that object
    prefix: str = ""              # envFrom prefix
    # The line this variable is declared on, so a claim derived from it cites
    # the line that asserts it. Without this every env claim cited the
    # RESOURCE's header line: the visits-service edge to wavefront-proxy was
    # true and cited line 7, `name: visits-service`, while the value naming
    # wavefront sat on line 58. A citation the reader cannot confirm at the
    # line it names is the promise this project makes, broken.
    line: int = 0
    optional: bool = False


@dataclass
class ContainerSpec:
    name: str
    image: str = ""
    image_line: int = 0
    ports: list[int] = field(default_factory=list)
    env: list[EnvBinding] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    is_init: bool = False


@dataclass
class ServicePort:
    port: int | None = None
    target_port: str | None = None
    name: str = ""
    protocol: str = "TCP"


@dataclass
class IngressRule:
    host: str = ""
    path: str = "/"
    path_type: str = ""
    backend_service: str = ""
    backend_port: str = ""


@dataclass
class ScaledTrigger:
    """One KEDA trigger — the queue/topic whose lag scales the workload.

    A trigger is *consumption evidence*: KEDA only scales on lag the workload
    is expected to drain, so a kafka/sqs trigger names a topic the target
    workload consumes even when the consuming code is unreadable.
    """
    type: str                     # kafka | aws-sqs-queue | rabbitmq | ...
    destination: str = ""         # topic / queue name ("" when not stated)
    consumer_group: str = ""
    queue_url: str = ""           # aws-sqs-queue queueURL as written


@dataclass
class GatewayRouteBinding:
    """One route rule from a gateway CRD (HTTPRoute, VirtualService,
    Traefik IngressRoute). All reduce to: requests matching PATH on HOSTS
    forward to BACKEND, possibly rewritten — the shape R4 consumes."""
    hosts: list[str] = field(default_factory=list)
    path: str = "/"
    path_type: str = ""           # prefix | exact | regex
    backend_service: str = ""
    backend_port: str = ""
    weight: int | None = None
    rewrite_to: str = ""          # ReplacePrefixMatch / Istio rewrite.uri
    strip_prefix: bool = False
    middlewares: list[str] = field(default_factory=list)


@dataclass
class K8sResource:
    name: str
    kind: str
    namespace: str = "default"
    api_version: str = ""
    labels: dict = field(default_factory=dict)
    annotations: dict = field(default_factory=dict)
    file_path: str = ""
    line: int = 0

    # Workloads
    containers: list[ContainerSpec] = field(default_factory=list)
    pod_labels: dict = field(default_factory=dict)
    service_account: str = ""
    schedule: str = ""                      # CronJob

    # Mesh / network policy
    policy_target: dict = field(default_factory=dict)
    policy_source_labels: list = field(default_factory=list)
    policy_source_accounts: list = field(default_factory=list)
    policy_action: str = ""

    # Service
    selector: dict = field(default_factory=dict)
    service_ports: list[ServicePort] = field(default_factory=list)
    service_type: str = ""
    external_name: str = ""

    # Ingress
    ingress_rules: list[IngressRule] = field(default_factory=list)
    ingress_class: str = ""

    # ConfigMap / Secret — key names only, never Secret values
    data_keys: list[str] = field(default_factory=list)
    config_values: dict = field(default_factory=dict)   # ConfigMap only

    # GitOps
    source_repo: str = ""
    source_path: str = ""
    source_revision: str = ""
    dest_namespace: str = ""

    # KEDA
    scale_target: str = ""
    triggers: list[ScaledTrigger] = field(default_factory=list)

    # Gateway CRDs
    route_bindings: list[GatewayRouteBinding] = field(default_factory=list)
    external_hosts: list[str] = field(default_factory=list)   # ServiceEntry
    strip_prefixes: list[str] = field(default_factory=list)   # Traefik Middleware

    @property
    def service_name_hint(self) -> str:
        """Best available service name for this resource.

        Conventional labels beat the object name because a Deployment is often
        called `orders-deploy` while every other system calls it `orders`.
        """
        for label in NAME_LABELS:
            value = self.labels.get(label) or self.pod_labels.get(label) or ""
            if value:
                return str(value)
        return self.name

    @property
    def all_env(self) -> list[EnvBinding]:
        return [binding for c in self.containers for binding in c.env]


def _line_of(content: str, needle: str) -> int:
    idx = content.find(needle)
    return content.count("\n", 0, idx) + 1 if idx >= 0 else 1




def _env_line(content: str, name: str) -> int:
    """The line declaring env var `name`, or 0 when it cannot be located.

    `- name: FOO` is how an entry in an env list is written, which
    distinguishes a variable declaration from the many other `name:` keys a
    manifest carries. Returns 0 rather than 1 on a miss, so the caller can
    fall back to the resource line instead of citing the top of the file.
    """
    if not content or not name:
        return 0
    for needle in (f"- name: {name}\n", f"- name: {name} ", f"- name: {name}"):
        idx = content.find(needle)
        if idx >= 0:
            return content.count("\n", 0, idx) + 1
    return 0


def _parse_env(container: dict, content: str = "") -> list[EnvBinding]:
    """env, envFrom and valueFrom."""
    bindings: list[EnvBinding] = []

    for entry in _as_list(container.get("env")):
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        name = _str(entry["name"])
        if "value" in entry:
            bindings.append(EnvBinding(name=name, source="literal",
                                       value=_str(entry.get("value")),
                                       line=_env_line(content, name)))
            continue
        source = entry.get("valueFrom")
        if not isinstance(source, dict):
            continue
        if ref := source.get("configMapKeyRef"):
            bindings.append(EnvBinding(
                name=name, source="configmap", ref_name=_str(ref.get("name")),
                ref_key=_str(ref.get("key")), optional=bool(ref.get("optional")),
                line=_env_line(content, name)))
        elif ref := source.get("secretKeyRef"):
            # Key name only: the value is a secret and never enters the graph.
            bindings.append(EnvBinding(
                name=name, source="secret", ref_name=_str(ref.get("name")),
                ref_key=_str(ref.get("key")), optional=bool(ref.get("optional")),
                line=_env_line(content, name)))
        elif ref := source.get("fieldRef"):
            bindings.append(EnvBinding(name=name, source="field",
                                       ref_key=_str(ref.get("fieldPath")),
                                       line=_env_line(content, name)))
        elif ref := source.get("resourceFieldRef"):
            bindings.append(EnvBinding(name=name, source="resource",
                                       ref_key=_str(ref.get("resource")),
                                       line=_env_line(content, name)))

    # envFrom imports every key of a ConfigMap/Secret; the individual names are
    # unknown here and get filled in by R9 once the referenced object is seen.
    for entry in _as_list(container.get("envFrom")):
        if not isinstance(entry, dict):
            continue
        prefix = _str(entry.get("prefix"))
        if ref := entry.get("configMapRef"):
            bindings.append(EnvBinding(
                name="*", source="configmap", ref_name=_str(ref.get("name")),
                prefix=prefix, optional=bool(ref.get("optional"))))
        elif ref := entry.get("secretRef"):
            bindings.append(EnvBinding(
                name="*", source="secret", ref_name=_str(ref.get("name")),
                prefix=prefix, optional=bool(ref.get("optional"))))
    return bindings


def _image_line(content: str, image: str) -> int:
    """The line declaring `image`, or 0 when it cannot be located.

    An image claim cited its workload's header, so the receipt for
    `busybox` in an initContainer named line 17 (`name: loadgenerator`)
    while the image sat on line 67.
    """
    if not content or not image:
        return 0
    for needle in (f"image: {image}\n", f"image: {image} ",
                   f'image: "{image}"', f"image: '{image}'"):
        at = content.find(needle)
        if at != -1:
            return content.count("\n", 0, at) + 1
    return 0


def _parse_containers(pod_spec: dict,
                      content: str = "") -> list[ContainerSpec]:
    containers: list[ContainerSpec] = []
    for key, is_init in (("initContainers", True), ("containers", False)):
        for raw in _as_list(pod_spec.get(key)):
            if not isinstance(raw, dict):
                continue
            ports = []
            for port in _as_list(raw.get("ports")):
                if isinstance(port, dict) and isinstance(port.get("containerPort"), int):
                    ports.append(port["containerPort"])
            containers.append(ContainerSpec(
                name=_str(raw.get("name")),
                image=_str(raw.get("image")),
                image_line=_image_line(content, _str(raw.get("image"))),
                ports=ports,
                env=_parse_env(raw, content),
                command=[_str(c) for c in _as_list(raw.get("command"))],
                args=[_str(a) for a in _as_list(raw.get("args"))],
                is_init=is_init,
            ))
    return containers


def _pod_template(spec: dict, kind: str) -> dict:
    """Locate the pod spec; CronJob nests it one level deeper."""
    if kind == "Pod":
        return spec
    if kind == "CronJob":
        job = (spec.get("jobTemplate") or {}).get("spec") or {}
        return (job.get("template") or {}).get("spec") or {}
    return (spec.get("template") or {}).get("spec") or {}


def _pod_labels(spec: dict, kind: str) -> dict:
    if kind == "Pod":
        return {}
    if kind == "CronJob":
        job = (spec.get("jobTemplate") or {}).get("spec") or {}
        template = job.get("template") or {}
    else:
        template = spec.get("template") or {}
    if not isinstance(template, dict):
        return {}
    return (template.get("metadata") or {}).get("labels") or {}


def _parse_network_policy(resource: K8sResource, spec: dict) -> None:
    """Who may talk to whom, per the cluster's own firewall."""
    resource.policy_target = dict(
        (spec.get("podSelector") or {}).get("matchLabels") or {})
    for rule in spec.get("ingress") or []:
        for source in rule.get("from") or []:
            labels = ((source.get("podSelector") or {})
                      .get("matchLabels") or {})
            if labels:
                resource.policy_source_labels.append(dict(labels))
    resource.policy_action = "ALLOW"


def _parse_authorization_policy(resource: K8sResource, spec: dict) -> None:
    """Istio AuthorizationPolicy: principals name source service accounts."""
    resource.policy_target = dict(
        (spec.get("selector") or {}).get("matchLabels") or {})
    resource.policy_action = str(spec.get("action") or "ALLOW").upper()
    for rule in spec.get("rules") or []:
        for source in rule.get("from") or []:
            for principal in (source.get("source") or {}).get(
                    "principals") or []:
                # cluster.local/ns/<ns>/sa/<name> — the sa segment is the
                # source's identity; anything else is not one.
                parts = str(principal).split("/")
                if "sa" in parts:
                    resource.policy_source_accounts.append(
                        parts[parts.index("sa") + 1])


def _parse_service(resource: K8sResource, spec: dict) -> None:
    resource.selector = spec.get("selector") or {}
    resource.service_type = _str(spec.get("type"))
    resource.external_name = _str(spec.get("externalName"))
    for port in _as_list(spec.get("ports")):
        if not isinstance(port, dict):
            continue
        resource.service_ports.append(ServicePort(
            port=port.get("port") if isinstance(port.get("port"), int) else None,
            target_port=_str(port.get("targetPort")) or None,
            name=_str(port.get("name")),
            protocol=_str(port.get("protocol")) or "TCP",
        ))


def _parse_ingress(resource: K8sResource, spec: dict) -> None:
    resource.ingress_class = _str(spec.get("ingressClassName"))
    default_backend = spec.get("defaultBackend") or {}
    if isinstance(default_backend, dict) and (service := default_backend.get("service")):
        port = service.get("port") or {}
        resource.ingress_rules.append(IngressRule(
            path="/", backend_service=_str(service.get("name")),
            backend_port=_str(port.get("number") or port.get("name")),
        ))
    for rule in _as_list(spec.get("rules")):
        if not isinstance(rule, dict):
            continue
        host = _str(rule.get("host"))
        http = rule.get("http") or {}
        for path_entry in _as_list(http.get("paths")):
            if not isinstance(path_entry, dict):
                continue
            backend = path_entry.get("backend") or {}
            service = backend.get("service") or {}
            port = service.get("port") or {}
            resource.ingress_rules.append(IngressRule(
                host=host,
                path=_str(path_entry.get("path")) or "/",
                path_type=_str(path_entry.get("pathType")),
                backend_service=(_str(service.get("name"))
                                 or _str(backend.get("serviceName"))),
                backend_port=_str(port.get("number") or port.get("name")
                                  or backend.get("servicePort")),
            ))


def _parse_gitops(resource: K8sResource, spec: dict) -> None:
    """ArgoCD Application / Flux source binding."""
    source = spec.get("source") or {}
    sources = spec.get("sources")
    if not source and isinstance(sources, list) and sources:
        source = sources[0] if isinstance(sources[0], dict) else {}
    resource.source_repo = _str(source.get("repoURL") or spec.get("url"))
    resource.source_path = _str(source.get("path") or spec.get("path"))
    resource.source_revision = _str(source.get("targetRevision")
                                    or (spec.get("ref") or {}).get("branch"))
    destination = spec.get("destination") or {}
    resource.dest_namespace = _str(destination.get("namespace")
                                   or spec.get("targetNamespace"))
    chart = spec.get("chart") or {}
    if isinstance(chart, dict) and not resource.source_repo:
        source_ref = (chart.get("spec") or {}).get("sourceRef") or {}
        resource.source_repo = _str(source_ref.get("name"))
    source_ref = spec.get("sourceRef") or {}
    if isinstance(source_ref, dict) and not resource.source_repo:
        resource.source_repo = _str(source_ref.get("name"))


def _parse_scaled_object(resource: K8sResource, spec: dict) -> None:
    """KEDA ScaledObject/ScaledJob."""
    target = spec.get("scaleTargetRef") or spec.get("jobTargetRef") or {}
    if isinstance(target, dict):
        resource.scale_target = _str(target.get("name"))
    for trigger in _as_list(spec.get("triggers")):
        if not isinstance(trigger, dict):
            continue
        metadata = trigger.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        trigger_type = _str(trigger.get("type")).lower()
        destination = _str(metadata.get("topic") or metadata.get("queueName")
                           or metadata.get("queue"))
        resource.triggers.append(ScaledTrigger(
            type=trigger_type,
            destination=destination,
            consumer_group=_str(metadata.get("consumerGroup")
                                or metadata.get("group")),
            queue_url=_str(metadata.get("queueURL") or metadata.get("queueURLs")),
        ))


def _parse_httproute(resource: K8sResource, spec: dict) -> None:
    """Gateway API HTTPRoute/GRPCRoute incl. URLRewrite filters."""
    hosts = [_str(h) for h in _as_list(spec.get("hostnames")) if _str(h)]
    for rule in _as_list(spec.get("rules")):
        if not isinstance(rule, dict):
            continue
        paths: list[tuple[str, str]] = []
        for match in _as_list(rule.get("matches")):
            if not isinstance(match, dict):
                continue
            if path := match.get("path"):
                kind = _str(path.get("type")) or "PathPrefix"
                paths.append((_str(path.get("value")) or "/",
                              {"PathPrefix": "prefix", "Exact": "exact",
                               "RegularExpression": "regex"}.get(kind, "prefix")))
            elif method := match.get("method"):
                # GRPCRoute: service/method match maps onto the wire path.
                service = _str(method.get("service"))
                rpc = _str(method.get("method"))
                paths.append((f"/{service}/{rpc}".rstrip("/"), "exact"))
        if not paths:
            paths = [("/", "prefix")]

        rewrite_to, strip = "", False
        for filt in _as_list(rule.get("filters")):
            if not isinstance(filt, dict) or _str(filt.get("type")) != "URLRewrite":
                continue
            path_rewrite = (filt.get("urlRewrite") or {}).get("path") or {}
            rewrite_to = _str(path_rewrite.get("replacePrefixMatch")
                              or path_rewrite.get("replaceFullPath"))
            strip = rewrite_to in ("/", "")

        for backend in _as_list(rule.get("backendRefs")):
            if not isinstance(backend, dict):
                continue
            for path, path_type in paths:
                resource.route_bindings.append(GatewayRouteBinding(
                    hosts=hosts, path=path, path_type=path_type,
                    backend_service=_str(backend.get("name")),
                    backend_port=_str(backend.get("port")),
                    weight=backend.get("weight") if isinstance(
                        backend.get("weight"), int) else None,
                    rewrite_to=rewrite_to, strip_prefix=strip,
                ))


def _parse_virtual_service(resource: K8sResource, spec: dict) -> None:
    """Istio VirtualService route table."""
    hosts = [_str(h) for h in _as_list(spec.get("hosts")) if _str(h)]
    for http in _as_list(spec.get("http")):
        if not isinstance(http, dict):
            continue
        paths: list[tuple[str, str]] = []
        for match in _as_list(http.get("match")):
            if not isinstance(match, dict):
                continue
            uri = match.get("uri") or {}
            if isinstance(uri, dict) and uri:
                if "prefix" in uri:
                    paths.append((_str(uri["prefix"]), "prefix"))
                elif "exact" in uri:
                    paths.append((_str(uri["exact"]), "exact"))
                elif "regex" in uri:
                    paths.append((_str(uri["regex"]), "regex"))
        if not paths:
            paths = [("/", "prefix")]
        rewrite = http.get("rewrite") or {}
        rewrite_to = _str(rewrite.get("uri")) if isinstance(rewrite, dict) else ""

        for route in _as_list(http.get("route")):
            if not isinstance(route, dict):
                continue
            destination = route.get("destination") or {}
            host = _str(destination.get("host"))
            port = destination.get("port") or {}
            for path, path_type in paths:
                resource.route_bindings.append(GatewayRouteBinding(
                    hosts=hosts, path=path, path_type=path_type,
                    backend_service=host.split(".")[0],
                    backend_port=_str(port.get("number")) if isinstance(
                        port, dict) else "",
                    weight=route.get("weight") if isinstance(
                        route.get("weight"), int) else None,
                    rewrite_to=rewrite_to, strip_prefix=bool(rewrite_to),
                ))


def _parse_ingressroute(resource: K8sResource, spec: dict) -> None:
    """Traefik IngressRoute CRD: rule expression + services."""
    for route in _as_list(spec.get("routes")):
        if not isinstance(route, dict):
            continue
        match = _str(route.get("match"))
        hosts = _TRAEFIK_HOST.findall(match)
        path_match = _TRAEFIK_PATH.search(match)
        path = path_match.group(2) if path_match else "/"
        path_type = "exact" if path_match and path_match.group(1) == "Path" else "prefix"
        middlewares = [_str(m.get("name")) for m in _as_list(route.get("middlewares"))
                       if isinstance(m, dict) and _str(m.get("name"))]
        for service in _as_list(route.get("services")):
            if not isinstance(service, dict):
                continue
            resource.route_bindings.append(GatewayRouteBinding(
                hosts=hosts, path=path, path_type=path_type,
                backend_service=_str(service.get("name")),
                backend_port=_str(service.get("port")),
                weight=service.get("weight") if isinstance(
                    service.get("weight"), int) else None,
                middlewares=middlewares,
            ))


def parse_kubernetes_yaml(file_path: str, content: str) -> list[K8sResource]:
    """Parse one or many YAML documents into typed K8s resources."""
    resources: list[K8sResource] = []
    try:
        documents = list(yaml.safe_load_all(content))
    except yaml.YAMLError as exc:
        # Un-rendered Helm templates are not valid YAML; that is expected.
        logger.debug("Not parseable as K8s YAML %s: %s", file_path, exc)
        return resources

    for document in documents:
        if not isinstance(document, dict):
            continue
        kind = _str(document.get("kind"))
        if kind not in K8S_KINDS:
            continue

        metadata = document.get("metadata") or {}
        spec = document.get("spec") or {}
        if not isinstance(metadata, dict) or not isinstance(spec, dict):
            continue

        name = _str(metadata.get("name")) or "unknown"
        resource = K8sResource(
            name=name,
            kind=kind,
            namespace=_str(metadata.get("namespace")) or "default",
            api_version=_str(document.get("apiVersion")),
            labels=metadata.get("labels") or {},
            annotations=metadata.get("annotations") or {},
            file_path=file_path,
            line=_line_of(content, f"name: {name}"),
        )

        if kind in WORKLOAD_KINDS:
            resource.containers = _parse_containers(_pod_template(spec, kind),
                                        content)
            resource.pod_labels = _pod_labels(spec, kind)
            resource.service_account = _str(
                _pod_template(spec, kind).get("serviceAccountName"))
            resource.schedule = _str(spec.get("schedule"))
        elif kind == "Service":
            _parse_service(resource, spec)
        elif kind == "NetworkPolicy":
            _parse_network_policy(resource, spec)
        elif kind == "AuthorizationPolicy":
            _parse_authorization_policy(resource, spec)
        elif kind == "Ingress":
            _parse_ingress(resource, spec)
        elif kind in ("ConfigMap", "Secret"):
            data = document.get("data") or {}
            string_data = document.get("stringData") or {}
            if isinstance(data, dict):
                resource.data_keys = [str(k) for k in data]
                if kind == "ConfigMap":
                    # Kept for ConfigMaps only, and redacted at ingestion.
                    resource.config_values = {str(k): _str(v)
                                              for k, v in data.items()}
            if isinstance(string_data, dict):
                resource.data_keys += [str(k) for k in string_data]
        elif kind in ("Application", "ApplicationSet", "Kustomization",
                      "HelmRelease"):
            _parse_gitops(resource, spec)
        elif kind in ("ScaledObject", "ScaledJob"):
            _parse_scaled_object(resource, spec)
        elif kind in ("HTTPRoute", "GRPCRoute"):
            _parse_httproute(resource, spec)
        elif kind == "VirtualService":
            _parse_virtual_service(resource, spec)
        elif kind == "IngressRoute":
            _parse_ingressroute(resource, spec)
        elif kind == "ServiceEntry":
            resource.external_hosts = [_str(h) for h in
                                       _as_list(spec.get("hosts")) if _str(h)]
        elif kind == "Middleware":
            strip = spec.get("stripPrefix") or {}
            if isinstance(strip, dict):
                resource.strip_prefixes = [_str(p) for p in
                                           _as_list(strip.get("prefixes"))
                                           if _str(p)]

        resources.append(resource)
    return resources


def parse_helm_chart(file_path: str, content: str) -> list[K8sResource]:
    """Chart.yaml identity plus declared chart dependencies."""
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict) or not data.get("name"):
        return []
    resource = K8sResource(
        name=_str(data["name"]), kind="HelmChart", file_path=file_path,
        annotations={"version": _str(data.get("version")),
                     "appVersion": _str(data.get("appVersion"))},
    )
    for dep in _as_list(data.get("dependencies")):
        if isinstance(dep, dict) and dep.get("name"):
            resource.data_keys.append(_str(dep["name"]))
    return [resource]


def flatten_values(data, prefix: str = "") -> dict:
    """Flatten nested Helm values into dotted keys.

    ``image: {repository: foo, tag: "1.2"}`` becomes
    ``{"image.repository": "foo", "image.tag": "1.2"}`` so a value can be joined
    the same way a flat config entry is. Lists are indexed, because
    ``env[0].value`` is a real place service URLs hide.
    """
    flat: dict = {}
    if isinstance(data, dict):
        for key, value in data.items():
            flat.update(flatten_values(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            flat.update(flatten_values(value, f"{prefix}[{index}]"))
    elif prefix and data is not None:
        flat[prefix] = _str(data)
    return flat


def parse_helm_values(file_path: str, content: str) -> list[K8sResource]:
    """Flatten a Helm values file.

    Values files are where a chart's image repository and every service URL,
    broker address and queue name actually get their per-environment value, so
    the flattened keys become config definitions downstream.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    values = flatten_values(data)
    if not values:
        return []
    return [K8sResource(
        name=_str(data.get("name")) or _str(data.get("nameOverride")) or "values",
        kind="HelmValues",
        file_path=file_path,
        data_keys=sorted(values),
        config_values=values,
        # An overlay file (values-prod.yaml) names the environment it configures.
        annotations={"environment": _values_environment(file_path)},
    )]


def _values_environment(file_path: str) -> str:
    """Environment a values file targets, from its filename."""
    stem = file_path.split("/")[-1].rsplit(".", 1)[0].lower()
    for sep in ("values-", "values_", "values."):
        if stem.startswith(sep):
            candidate = stem[len(sep):]
            if candidate:
                return candidate
    return ""


def parse_k8s_file(file_path: str, content: str) -> list[K8sResource]:
    file_name = file_path.split("/")[-1]
    if file_name in ("Chart.yaml", "Chart.yml"):
        return parse_helm_chart(file_path, content)
    if file_name.startswith("values") and file_name.endswith((".yaml", ".yml")):
        return parse_helm_values(file_path, content)
    return parse_kubernetes_yaml(file_path, content)
