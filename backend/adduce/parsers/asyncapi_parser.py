"""Messaging contract declarations: AsyncAPI + Avro.

Messaging is where cross-repo edges hide hardest: producer and consumer share
no import, no URL, no RPC key — only a topic string both sides spell
independently. An AsyncAPI document is the one place a repo *declares* that
string together with its direction, which upgrades topic edges from
origin=inferred to origin=declared. Avro `.avsc` files add the
payload layer: Schema Registry's TopicNameStrategy names subjects
`<topic>-value` / `<topic>-key`, so a schema file following that convention
carries a topic hint in its own file name.

CRITICAL semantic mapping — the most-confused part of AsyncAPI. A document
describes ONE application, and in 2.x the verbs are written from the
*client's* perspective, not the application's:

  - 2.x ``channels.<name>.publish``   -> OTHERS may publish here, the app
    RECEIVES -> action "consumes".
  - 2.x ``channels.<name>.subscribe`` -> others subscribe to what the app
    sends -> action "produces".

AsyncAPI 3.x fixed the inversion with top-level ``operations``:

  - ``action: send``    -> the app sends    -> "produces".
  - ``action: receive`` -> the app receives -> "consumes".

3.x operations reference channels via ``channel.$ref: '#/channels/X'``; the
wire address is ``channels.X.address``, falling back to the channel key when
address is absent or null (3.x uses ``address: null`` for "decided at
runtime"). Parsing is defensive throughout: malformed input yields None or
empty results, never an exception.
"""

import json
import logging
import re
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)

# Sniff for a top-level "asyncapi:" key. `[{\s]{0,6}` admits single-line and
# pretty-printed JSON (`{"asyncapi": ...}`) while keeping deeply nested YAML
# keys out; parse_asyncapi is the authority behind the sniff.
_ASYNCAPI_KEY = re.compile(r"^[{\s]{0,6}['\"]?asyncapi['\"]?\s*:", re.MULTILINE)

# Broker protocols the linker can key on; everything else is noise here.
_PROTOCOLS = {
    "kafka": "kafka", "kafka-secure": "kafka",
    "amqp": "amqp", "amqps": "amqp",
    "sqs": "sqs", "sns": "sns",
}
_V3_ACTIONS = {"send": "produces", "receive": "consumes"}
_V2_VERBS = (("publish", "consumes"), ("subscribe", "produces"))


@dataclass
class ChannelOperation:
    channel: str        # channel key/name in the document
    address: str        # resolved topic/queue address (v3 channels.X.address, else channel key)
    action: str         # "produces" | "consumes" (from THIS application's perspective)
    protocol: str = ""  # kafka | sqs | sns | amqp | "" (servers or channel bindings)


@dataclass
class AsyncAPIDoc:
    title: str = ""
    version: str = ""                # asyncapi spec version string
    operations: list[ChannelOperation] = field(default_factory=list)
    declared_channels: list[str] = field(default_factory=list)  # every address, even without ops


def _load_document(content: str):
    """YAML first (a superset of most JSON), raw JSON as fallback.

    The fallback matters: JSON permits tab whitespace that YAML rejects, so a
    machine-written .json document can fail safe_load while being valid JSON.
    """
    if not content or not isinstance(content, str):
        return None
    try:
        return yaml.safe_load(content)
    except yaml.YAMLError:
        pass
    try:
        return json.loads(content)
    except ValueError:
        return None


def _normalize_protocol(value) -> str:
    return _PROTOCOLS.get(str(value).lower(), "") if isinstance(value, str) else ""


def _servers_protocol(data: dict) -> str:
    """Document-level default: first recognized broker protocol in `servers`."""
    servers = data.get("servers")
    if not isinstance(servers, dict):
        return ""
    for server in servers.values():
        if isinstance(server, dict):
            if protocol := _normalize_protocol(server.get("protocol")):
                return protocol
    return ""


def _bindings_protocol(node) -> str:
    """A `bindings.kafka` (etc.) block names its protocol by key."""
    if not isinstance(node, dict):
        return ""
    bindings = node.get("bindings")
    if not isinstance(bindings, dict):
        return ""
    for key in bindings:
        if protocol := _normalize_protocol(key):
            return protocol
    return ""


def _parse_v2(data: dict, default_protocol: str):
    """2.x: operations nest inside channels; the channel key is the address.

    Parameterized keys like `user/{userId}/events` keep their braces — the
    literal template is what both sides of the contract declare.
    """
    operations: list[ChannelOperation] = []
    declared: list[str] = []
    channels = data.get("channels")
    if not isinstance(channels, dict):
        return operations, declared
    for key, channel in channels.items():
        address = str(key)
        declared.append(address)
        if not isinstance(channel, dict):
            continue
        channel_protocol = _bindings_protocol(channel) or default_protocol
        for verb, action in _V2_VERBS:
            if verb not in channel:
                continue
            protocol = _bindings_protocol(channel.get(verb)) or channel_protocol
            operations.append(ChannelOperation(
                channel=address, address=address, action=action,
                protocol=protocol))
    return operations, declared


def _ref_channel_key(channel_ref) -> str:
    """Channel key out of a 3.x `channel.$ref: '#/channels/X'`.

    JSON-pointer unescape per RFC 6901: a channel key containing "/" arrives
    as "~1" (and "~" as "~0"), in that replacement order.
    """
    if not isinstance(channel_ref, dict):
        return ""
    ref = channel_ref.get("$ref")
    if not isinstance(ref, str) or "#" not in ref:
        return ""
    pointer = ref.split("#", 1)[1]
    prefix = "/channels/"
    raw = pointer[len(prefix):] if pointer.startswith(prefix) \
        else pointer.rsplit("/", 1)[-1]
    return raw.replace("~1", "/").replace("~0", "~")


def _parse_v3(data: dict, default_protocol: str):
    """3.x: top-level `operations` with send/receive referencing channels."""
    operations: list[ChannelOperation] = []
    declared: list[str] = []
    addresses: dict[str, str] = {}
    channel_protocols: dict[str, str] = {}

    channels = data.get("channels")
    for key, channel in (channels.items() if isinstance(channels, dict) else ()):
        key = str(key)
        address = key
        if isinstance(channel, dict):
            raw = channel.get("address")
            if isinstance(raw, str) and raw:   # absent or null -> channel key
                address = raw
            channel_protocols[key] = _bindings_protocol(channel)
        addresses[key] = address
        declared.append(address)

    ops = data.get("operations")
    for operation in (ops.values() if isinstance(ops, dict) else ()):
        if not isinstance(operation, dict):
            continue
        action = _V3_ACTIONS.get(str(operation.get("action") or "").lower())
        key = _ref_channel_key(operation.get("channel"))
        if action is None or not key:
            continue   # decline, don't guess: no direction or no channel
        protocol = (_bindings_protocol(operation)
                    or channel_protocols.get(key, "") or default_protocol)
        operations.append(ChannelOperation(
            channel=key, address=addresses.get(key, key), action=action,
            protocol=protocol))
    return operations, declared


def parse_asyncapi(file_path: str, content: str) -> AsyncAPIDoc | None:
    """Parse one AsyncAPI document; None if it is not one."""
    data = _load_document(content)
    if not isinstance(data, dict) or "asyncapi" not in data:
        if data is not None:
            logger.debug("not an AsyncAPI document: %s", file_path)
        return None
    raw_version = data.get("asyncapi")
    version = str(raw_version) if isinstance(raw_version, (str, int, float)) else ""
    info = data.get("info")
    title = str(info.get("title") or "") if isinstance(info, dict) else ""

    default_protocol = _servers_protocol(data)
    if version.split(".", 1)[0].strip() == "3":
        operations, declared = _parse_v3(data, default_protocol)
    else:
        operations, declared = _parse_v2(data, default_protocol)
    return AsyncAPIDoc(
        title=title, version=version, operations=operations,
        declared_channels=list(dict.fromkeys(declared)))


def is_asyncapi_file(file_name: str, content: str) -> bool:
    """Cheap sniff: asyncapi* file name, or a top-level `asyncapi:` key."""
    name = (file_name or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.startswith("asyncapi") and name.endswith((".yaml", ".yml", ".json")):
        return True
    return bool(content) and bool(_ASYNCAPI_KEY.search(content))


@dataclass
class AvroSchema:
    name: str
    namespace: str
    full_name: str          # namespace.name
    subject_hint: str = ""  # "orders-value" style, from the file name only


def _first_record(data):
    """Top-level record, or first record inside a top-level union list."""
    if isinstance(data, dict) and data.get("type") == "record":
        return data
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("type") == "record":
                return item
    return None


def _subject_hint(file_path: str) -> str:
    """Registry TopicNameStrategy: `orders-value.avsc` names subject orders-value.

    Only the `-value` / `-key` suffix convention is trusted — any other file
    name says nothing about the subject, so the hint stays empty.
    """
    stem = (file_path or "").replace("\\", "/").rsplit("/", 1)[-1]
    if stem.endswith(".avsc"):
        stem = stem[:-len(".avsc")]
    return stem if stem.endswith(("-value", "-key")) else ""


def parse_avro_schema(file_path: str, content: str) -> AvroSchema | None:
    """Parse a JSON .avsc into its declared identity; None unless a record."""
    if not content or not isinstance(content, str):
        return None
    try:
        data = json.loads(content)
    except ValueError:
        return None
    record = _first_record(data)
    if record is None:
        return None
    name = record.get("name")
    if not isinstance(name, str) or not name:
        return None
    namespace = record.get("namespace")
    namespace = namespace if isinstance(namespace, str) else ""
    # Avro fullname rule: a dotted name IS the fullname; any namespace
    # attribute alongside it is ignored.
    if "." in name:
        namespace, _, name = name.rpartition(".")
    full_name = f"{namespace}.{name}" if namespace else name
    return AvroSchema(
        name=name, namespace=namespace, full_name=full_name,
        subject_hint=_subject_hint(file_path))


def is_avro_schema_file(file_name: str) -> bool:
    return file_name.endswith(".avsc")
