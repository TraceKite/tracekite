"""Config-definition emitters: env bindings, ConfigMaps, Helm values.

Extracted from `ingest_claims.py` while adding a layer: a ConfigMap
or env value that is a pure Helm reference (`{{ .Values.backend.url }}`)
now records WHICH values key it points at (`helm_ref`), so R9 can follow
values → ConfigMap → env → code instead of stopping one layer short.
Secret values are never read; a Secret's helm_ref is still just a key
name, but its VALUE class stays `secret` and joins nothing.
"""

from tracekite.parsers.helm_refs import helm_value_ref
from tracekite.services.claim_sink import add_claim
from tracekite.services.claims import (
    CONSUMES, PROVIDES, ContractClaim, config_key,
)
from tracekite.services.env_extractor import looks_like_endpoint_var
from tracekite.services.redaction import redact
from tracekite.utils.evidence import evidence_path


def emit_env_binding(repo_id, resource, service, scope, environment, evidence,
                     evidence_node, binding, sink) -> None:
    """One container env var.

    Literals are joinable now; configmap/secret references are recorded as
    unresolved and completed by R9 once the referenced object is seen.
    """
    if binding.name == "*":
        # envFrom: the individual key names live on the referenced object.
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="cfgread", direction=CONSUMES,
            key=config_key(scope, f"{binding.ref_name}/*"),
            hint_source="config", evidence=evidence, env_scope=environment,
            subject=f"{resource.kind}/{resource.name}",
            attrs={"source": "k8s_envfrom", "ref_kind": binding.source,
                   "ref_name": binding.ref_name, "prefix": binding.prefix,
                   "service": service, "namespace": resource.namespace},
        ), evidence_node, sink)
        return

    if binding.line and evidence:
        # Cite the line DECLARING this variable, not the resource header.
        # The edge visits-service -> wavefront-proxy was true and cited
        # line 7 (`name: visits-service`) while the value naming wavefront
        # sat on line 58 — a receipt the reader cannot confirm at the line
        # it names. Claim ids hash the evidence PATH only, so a better line
        # never churns identity.
        evidence = [f"{evidence_path(evidence[0])}:{binding.line}"]

    attrs = {"source": "k8s_env", "env_name": binding.name,
             "binding": binding.source, "service": service,
             "namespace": resource.namespace,
             "endpoint_like": looks_like_endpoint_var(binding.name)}
    if resource.schedule:
        # A CronJob's calls are time-triggered; the edge downstream carries
        # the trigger so a 03:00 dependency is not mistaken for a live one.
        attrs["schedule"] = resource.schedule

    if binding.source == "literal":
        redacted = redact(binding.name, binding.value or "")
        attrs.update({"value_class": redacted.value_class,
                      "value_host": redacted.value_host or "",
                      "value_port": redacted.value_port or 0,
                      "value_scheme": redacted.value_scheme or "",
                      "value_path_prefix": redacted.value_path_prefix or "",
                      "value_hmac": redacted.value_hmac})
        ref = helm_value_ref(binding.value or "")
        if ref:
            attrs["helm_ref"] = ref
        elif "{{" in (binding.value or ""):
            attrs["helm_composite"] = True
    else:
        attrs.update({"ref_kind": binding.source, "ref_name": binding.ref_name,
                      "ref_key": binding.ref_key, "unresolved": True})

    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="cfgdef", direction=PROVIDES,
        key=config_key(scope, binding.name), hint_source="config",
        evidence=evidence, env_scope=environment, attrs=attrs,
        subject=f"{resource.kind}/{resource.name}",
    ), evidence_node, sink)


def emit_config_object(repo_id, resource, scope, environment, evidence,
                       evidence_node, sink) -> None:
    """ConfigMap/Secret key definitions. Secret values never read."""
    for key in resource.data_keys:
        attrs = {"source": f"k8s_{resource.kind.lower()}",
                 "object": resource.name, "namespace": resource.namespace,
                 "config_key": key,
                 "endpoint_like": looks_like_endpoint_var(key)}
        if resource.kind == "ConfigMap":
            raw = resource.config_values.get(key, "")
            redacted = redact(key, raw)
            attrs.update({"value_class": redacted.value_class,
                          "value_host": redacted.value_host or "",
                          "value_port": redacted.value_port or 0,
                          "value_scheme": redacted.value_scheme or "",
                          "value_path_prefix": redacted.value_path_prefix or "",
                          "value_hmac": redacted.value_hmac})
            ref = helm_value_ref(raw)  # a pointer, not a value
            if ref:
                attrs["helm_ref"] = ref
            elif "{{" in raw:
                attrs["helm_composite"] = True
        else:
            attrs["value_class"] = "secret"
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="cfgdef", direction=PROVIDES,
            key=config_key(scope, f"{resource.name}/{key}"),
            hint_source="config", evidence=evidence, env_scope=environment,
            attrs=attrs, subject=f"{resource.kind}/{resource.name}",
        ), evidence_node, sink)


def emit_helm_values(repo_id, resource, environment, evidence, evidence_node,
                     sink) -> None:
    """Flattened Helm values as config definitions."""
    for key, value in resource.config_values.items():
        redacted = redact(key, value)
        # Network-shaped values are always joinable; enum-ish ones only when
        # the key itself says "message destination" — otherwise every Helm
        # scalar would become a claim.
        if redacted.value_class not in ("url", "hostname") and not (
                redacted.value_class == "enum-ish" and _topicish_key(key)):
            continue
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="cfgdef", direction=PROVIDES,
            key=config_key(repo_id, key), hint_source="config",
            evidence=evidence, env_scope=environment,
            subject=f"HelmValues/{resource.name}",
            attrs={"source": "helm_values", "config_key": key,
                   "value_class": redacted.value_class,
                   "value_host": redacted.value_host or "",
                   "value_port": redacted.value_port or 0,
                   "value_scheme": redacted.value_scheme or "",
                   "value_hmac": redacted.value_hmac,
                   "endpoint_like": True},
        ), evidence_node, sink)


_TOPICISH_KEY_TOKENS = ("topic", "queue", "stream", "channel", "destination",
                        "subject", "binding")


def _topicish_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in _TOPICISH_KEY_TOKENS)
