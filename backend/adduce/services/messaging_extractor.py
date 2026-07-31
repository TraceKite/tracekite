"""Messaging producer/consumer sites in source code.

Async edges never appear in HTTP call graphs: a Kafka topic or SQS queue is the
only join key between the service that writes it and the service that reads it.
These extractors record who produces and who consumes which destination so the
linker can meet both halves, exactly as gRPC sites meet on the service name.

Precision-first: a fabricated destination creates a false edge between two
services, which is worse than no edge. When the topic/queue argument is a
variable or expression the site is emitted with ``dynamic=True`` and an empty
destination — we never chase assignments. When the argument is an env read
(``process.env.X``, ``os.environ["X"]``, ``System.getenv("X")``, ...) the env
var name is recorded instead, so R9 can resolve it against config ownership.

Queue URLs keep only the last path segment and ARNs the last ``:`` segment,
with ``attrs`` markers (``from_url`` / ``arn``) so the linker can weight the
stronger forms of evidence.

Regex rather than AST for the same reason as env_extractor: these are
single-expression idioms stable across framework versions, and a file with a
partial parse must still yield its messaging sites.
"""

import re
from dataclasses import dataclass, field

# --- argument classification ------------------------------------------------

# Env reads accepted as a destination indirection. Only reads whose var name is
# a literal count; os.environ.get is included because it is the same read.
_ENV_ARG = re.compile(
    r"process\.env\.([A-Za-z_]\w*)"
    r"|process\.env\[\s*['\"]([^'\"]+)['\"]\s*\]"
    r"|os\.environ\s*(?:\.get\s*\(|\[)\s*['\"]([^'\"]+)['\"]"
    r"|os\.getenv\s*\(\s*['\"]([^'\"]+)['\"]"
    r"|System\.getenv\s*\(\s*\"([^\"]+)\""
    r"|os\.Getenv\s*\(\s*\"([^\"]+)\""
    r"|Environment\.GetEnvironmentVariable\s*\(\s*\"([^\"]+)\"")

# Whole-expression string literal. The optional prefix admits Python f/r/b
# strings; an f-string with interpolation is dynamic, not a literal.
_STR_LIT = re.compile(r"^(?P<pre>[A-Za-z]{0,2})(?P<q>[\"'`])(?P<v>[^\"'`]*)(?P=q)$")
_REGEX_LIT = re.compile(r"^/.+/[a-z]*$")
_AWS_STRING_WRAP = re.compile(r"^aws\.String\s*\(\s*(.+?)\s*\)$")
_QUOTED = re.compile(r"[\"']([^\"']+)[\"']")
_PATTERN_HINT = re.compile(r"Pattern\.compile|\bpattern\s*=")

# --- JVM (java / kotlin / scala) -------------------------------------------

_JVM_KAFKA_LISTENER = re.compile(r"@KafkaListener\s*\(([^)]*)\)")
_JVM_TOPIC_PATTERN = re.compile(r"\btopicPattern\s*=\s*(\"[^\"]*\"|[^,)]+)")
_JVM_KAFKA_TEMPLATE_SEND = re.compile(
    r"(?i)\b\w*kafka\w*template\s*\.\s*send\s*\(\s*([^,)\n]+)")
_JVM_PRODUCER_RECORD = re.compile(
    r"\bnew\s+ProducerRecord\s*(?:<[^>]*>)?\s*\(\s*([^,)\n]+)")
_JVM_STREAMS_STREAM = re.compile(r"\b\w*[Bb]uilder\s*\.\s*stream\s*\(\s*([^,)\n]+)")
_JVM_STREAMS_TO = re.compile(r"\.\s*to\s*\(\s*([^,)\n]+)")
_JVM_STREAMS_THROUGH = re.compile(r"\.\s*through\s*\(\s*([^,)\n]+)")
_JVM_SUBSCRIBE = re.compile(r"(?i)\b\w*consumer\s*\.\s*subscribe\s*\(\s*([^;\n]*)")
_JVM_SQS_LISTENER = re.compile(r"@SqsListener\s*\(([^)]*)\)")
_JVM_SQS_TEMPLATE = re.compile(
    r"(?i)\b(?:\w*sqs\w*template|queuemessagingtemplate)\s*\.\s*"
    r"(?:convertandsend|send)\s*\(\s*([^,)\n]+)")
# Builder chains span lines; [^;]*? crosses newlines but never a statement.
_JVM_SQS_BUILDER = re.compile(
    r"\b(Send|Receive)Message(?:Batch)?Request\s*\.\s*builder\s*\(\s*\)"
    r"[^;]*?\.\s*queueUrl\s*\(\s*([^,)\n]+)")
_JVM_SNS_BUILDER = re.compile(
    r"\bPublishRequest\s*\.\s*builder\s*\(\s*\)[^;]*?\.\s*topicArn\s*\(\s*([^,)\n]+)")

# --- Node (javascript / typescript) -----------------------------------------

_NODE_KAFKAJS_SEND = re.compile(r"(?i)\b\w*producer\s*\.\s*send\s*\(\s*\{")
_NODE_KAFKAJS_SENDBATCH = re.compile(r"(?i)\b\w*producer\s*\.\s*sendBatch\s*\(")
_NODE_SUBSCRIBE = re.compile(r"(?i)\b\w*consumer\s*\.\s*subscribe\s*\(\s*")
_NODE_RDKAFKA_PRODUCE = re.compile(r"(?i)\b\w*producer\s*\.\s*produce\s*\(\s*([^,)\n]+)")
_NODE_NEST_PATTERN = re.compile(r"@(?:MessagePattern|EventPattern)\s*\(\s*([^,)\n]*)")
_NODE_NEST_EMIT = re.compile(r"(?i)\b\w*client\s*\.\s*(?:emit|send)\s*\(\s*([^,)\n]+)")
_NODE_V3_CMD = re.compile(
    r"\bnew\s+(SendMessage|ReceiveMessage|Publish)(?:Batch)?Command\s*\(\s*\{")
_NODE_V2_SQS = re.compile(r"(?i)\b\w*sqs\w*\s*\.\s*(sendMessage|receiveMessage)\s*\(\s*\{")
_NODE_V2_SNS = re.compile(r"(?i)\b\w*sns\w*\s*\.\s*publish\s*\(\s*\{")
# \btopic\s*: cannot match inside "topicMessages" (colon required right after).
_JS_TOPIC_KEY = re.compile(r"\btopic\s*:\s*(\[[^\]]*\]|[^,}\n]+)")
_JS_TOPICS_KEY = re.compile(r"\btopics?\s*:\s*(\[[^\]]*\]|[^,}\n]+)")
_JS_QUEUE_URL_KEY = re.compile(r"\bQueueUrl\s*:\s*([^,}\n]+)")
_JS_TOPIC_ARN_KEY = re.compile(r"\bTopicArn\s*:\s*([^,}\n]+)")

# --- Go ---------------------------------------------------------------------

_GO_SARAMA_PRODUCER_MSG = re.compile(
    r"sarama\.ProducerMessage\s*\{[^}]*?\bTopic:\s*([^,}\n]+)")
_GO_CONSUME_PARTITION = re.compile(r"\.\s*ConsumePartition\s*\(\s*([^,)\n]+)")
_GO_GROUP_CONSUME = re.compile(
    r"\.\s*Consume\s*\(\s*[\w.]+(?:\(\))?\s*,\s*"
    r"(?:\[\]string\s*\{([^}]*)\}|([\w.]+))\s*,")
_GO_SEGMENTIO_READER = re.compile(r"kafka\.ReaderConfig\s*\{")
_GO_SEGMENTIO_WRITER = re.compile(r"kafka\.(?:WriterConfig|Writer)\s*\{")
_GO_CONFLUENT_SUBSCRIBE = re.compile(
    r"\.\s*SubscribeTopics\s*\(\s*(?:\[\]string\s*\{([^}]*)\}|([\w.]+))")
_GO_CONFLUENT_TOPICPART = re.compile(
    r"kafka\.TopicPartition\s*\{[^}]*?\bTopic:\s*([^,}\n]+)")
_GO_SQS_INPUT = re.compile(r"sqs\.(SendMessage|ReceiveMessage)(?:Batch)?Input\s*\{")
_GO_SNS_PUBLISH = re.compile(r"sns\.PublishInput\s*\{")
_GO_TOPIC_FIELD = re.compile(r"\bTopic:\s*([^,}\n]+)")
_GO_QUEUE_URL_FIELD = re.compile(r"\bQueueUrl:\s*([^,}\n]+)")
_GO_TOPIC_ARN_FIELD = re.compile(r"\bTopicArn:\s*([^,}\n]+)")

# --- Python -----------------------------------------------------------------

_PY_PRODUCER_SEND = re.compile(
    r"(?i)\b\w*producer\s*\.\s*(send_and_wait|send|produce)\s*\(\s*"
    r"(?:topic\s*=\s*)?([^,)\n]+)")
_PY_KAFKA_CONSUMER = re.compile(r"\bKafkaConsumer\s*\(([^)]*)")
_PY_SUBSCRIBE = re.compile(r"(?i)\b\w*consumer\s*\.\s*subscribe\s*\(\s*([^)\n]*)")
_PY_FAUST_TOPIC = re.compile(r"\bapp\.topic\s*\(\s*([^,)\n]+)")
_PY_FAUST_AGENT = re.compile(r"@app\.agent\s*\(\s*([^)\n]*)\)")
_PY_BOTO3_SQS = re.compile(r"\.\s*(send_message|receive_message)\s*\(\s*([^)]*)")
_PY_BOTO3_GET_QUEUE = re.compile(
    r"\bget_queue_by_name\s*\(\s*(?:[^)]*?QueueName\s*=\s*)?([^,)\n]+)")
_PY_BOTO3_SNS = re.compile(r"\.\s*publish\s*\(\s*([^)]*)")
_PY_QUEUE_URL_KW = re.compile(r"\bQueueUrl\s*=\s*([^,)\n]+)")
_PY_TOPIC_ARN_KW = re.compile(r"\bTopicArn\s*=\s*([^,)\n]+)")

# --- C# ---------------------------------------------------------------------

_CS_PRODUCE = re.compile(r"(?i)\b\w*producer\s*\.\s*produce(?:async)?\s*\(\s*([^,)\n]+)")
_CS_SUBSCRIBE = re.compile(r"(?i)\b\w*consumer\s*\.\s*subscribe\s*\(\s*([^;\n]*)")
_CS_AWS_REQ = re.compile(
    r"\bnew\s+(SendMessage|ReceiveMessage|Publish)(?:Batch)?Request\s*"
    r"(?:\(\s*([^,)\n]*)[^)]*\))?\s*(\{?)")
_CS_SQS_SEND_ASYNC = re.compile(
    r"(?i)\b\w*sqs\w*\s*\.\s*sendmessage(?:batch)?async\s*\(\s*([^,)\n]+)")
_CS_QUEUE_URL_INIT = re.compile(r"\bQueueUrl\s*=\s*([^,}\n;]+)")
_CS_TOPIC_ARN_INIT = re.compile(r"\bTopicArn\s*=\s*([^,}\n;]+)")

# --- Spring Cloud Stream flat-config keys -----------------------------------

_SCS_DESTINATION = re.compile(r"^spring\.cloud\.stream\.bindings\.([^.]+)\.destination$")
_SCS_BINDER = re.compile(r"^spring\.cloud\.stream\.bindings\.([^.]+)\.binder$")
_SCS_SCOPED = re.compile(r"^spring\.cloud\.stream\.(kafka|rabbit)\.bindings\.([^.]+)\.")
_SPRING_KAFKA_DEFAULT_TOPIC = (
    "spring.kafka.template.default-topic", "spring.kafka.template.defaultTopic")


@dataclass
class MessagingSite:
    system: str        # "kafka" | "sqs" | "sns"
    destination: str   # topic/queue/binding name, "" when dynamic or env-indirected
    role: str          # "produces" | "consumes"
    line: int
    framework: str     # e.g. "spring-kafka", "kafkajs", "sarama", "boto3", ...
    env_var: str = ""  # env var name when destination is env-indirected
    dynamic: bool = False
    raw: str = ""      # matched text
    attrs: dict = field(default_factory=dict)


@dataclass
class StreamBinding:
    binding_name: str
    direction: str     # "produces" (out) | "consumes" (in)
    destination: str
    binder: str = ""   # kafka | rabbit | "" if unknown


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


def _classify_arg(expr: str) -> tuple[str, str, bool, dict]:
    """(destination, env_var, dynamic, attrs) for one argument expression."""
    expr = (expr or "").strip().rstrip(";,").strip()
    m = _AWS_STRING_WRAP.match(expr)
    if m:
        expr = m.group(1).strip()
    if expr.startswith("&"):
        expr = expr[1:].strip()
    if not expr:
        return "", "", True, {}
    m = _ENV_ARG.search(expr)
    if m:
        return "", next(g for g in m.groups() if g), False, {}
    if _REGEX_LIT.match(expr):
        return "", "", True, {"pattern": True}
    m = _STR_LIT.match(expr)
    if m:
        value = m.group("v")
        # Placeholders and interpolations name a config slot, not a topic.
        if "${" in value or "#{" in value:
            return "", "", True, {}
        if "f" in (m.group("pre") or "").lower() and "{" in value:
            return "", "", True, {}
        if not value:
            return "", "", True, {}
        return value, "", False, {}
    return "", "", True, {}


def _queue_ref(dest: str) -> tuple[str, dict]:
    """Normalize a queue URL / topic ARN to its bare name, keeping a marker."""
    if dest.startswith("arn:"):
        name = dest.rsplit(":", 1)[-1]
        return (name, {"arn": True}) if name else ("", {})
    if "://" in dest:
        path = dest.split("://", 1)[1].split("?")[0].rstrip("/")
        segments = path.split("/")
        name = segments[-1] if len(segments) > 1 else ""
        return (name, {"from_url": True}) if name else ("", {})
    return dest, {}


def _emit(sites: list[MessagingSite], content: str, pos: int, system: str,
          role: str, framework: str, *, arg: str | None = None, dest: str = "",
          attrs: dict | None = None, raw: str = "", queue_ref: bool = False,
          dynamic: bool = False) -> None:
    merged = dict(attrs or {})
    env = ""
    if arg is not None:
        dest, env, dynamic, arg_attrs = _classify_arg(arg)
        merged.update(arg_attrs)
        raw = raw or arg.strip()
    if dest and queue_ref:
        dest, ref_attrs = _queue_ref(dest)
        merged.update(ref_attrs)
        if not dest:
            dynamic = True
    sites.append(MessagingSite(
        system=system, destination=dest, role=role,
        line=_line_of(content, pos), framework=framework, env_var=env,
        dynamic=dynamic, raw=raw.strip(), attrs=merged))


def _emit_elements(sites: list[MessagingSite], content: str, pos: int,
                   system: str, role: str, framework: str, inner: str,
                   queue_ref: bool = False) -> None:
    """Each comma-separated element of a bracketed list, classified alone."""
    for part in (p.strip() for p in inner.split(",")):
        if part:
            _emit(sites, content, pos, system, role, framework, arg=part,
                  queue_ref=queue_ref)


def _emit_from_window(sites: list[MessagingSite], content: str, pos: int,
                      system: str, role: str, framework: str, window: str) -> None:
    """Freeform call-argument window: env reads first, then quoted names.

    Handles wrapper noise like ``List.of("a", "b")`` where comma-splitting
    breaks. A window with neither env reads nor literals is one dynamic site.
    """
    if _PATTERN_HINT.search(window):
        _emit(sites, content, pos, system, role, framework, dynamic=True,
              attrs={"pattern": True}, raw=window.strip())
        return
    emitted = False
    for m in _ENV_ARG.finditer(window):
        _emit(sites, content, pos, system, role, framework,
              arg=window[m.start():m.end() + 2])
        emitted = True
    remaining = _ENV_ARG.sub("", window)
    for m in _QUOTED.finditer(remaining):
        value = m.group(1)
        if "${" in value or "#{" in value:
            continue
        _emit(sites, content, pos, system, role, framework, dest=value, raw=value)
        emitted = True
    if not emitted and window.strip():
        _emit(sites, content, pos, system, role, framework, dynamic=True,
              raw=window.strip())


def _annotation_values(args: str, keys: tuple[str, ...]) -> list[str] | None:
    """Raw value expressions for any of `keys`, or the bare annotation value.

    None means the annotation names only unrelated keys, so the destination
    lives elsewhere and the site is dynamic.
    """
    for key in keys:
        m = re.search(rf"\b{key}\s*=\s*(\{{[^}}]*\}}|\[[^\]]*\]|[^,)]+)", args)
        if m:
            value = m.group(1).strip()
            if value[:1] in "{[":
                return [p.strip() for p in value[1:-1].split(",") if p.strip()]
            return [value]
    if "=" not in args:
        value = args.strip()
        if value[:1] in "{[":
            return [p.strip() for p in value[1:-1].split(",") if p.strip()]
        return [value] if value else []
    return None


def extract_messaging_sites(content: str, language: str | None) -> list[MessagingSite]:
    """Messaging producer/consumer sites in one file, de-duplicated."""
    if not content or not isinstance(content, str):
        return []
    lang = (language or "").lower()
    sites: list[MessagingSite] = []

    if lang in ("java", "kotlin", "scala"):
        _jvm(content, sites)
    elif lang in ("javascript", "typescript"):
        _node(content, sites)
    elif lang == "go":
        _go(content, sites)
    elif lang == "python":
        _python(content, sites)
    elif lang in ("c#", "csharp"):
        _csharp(content, sites)

    # First site wins per key; attrs from collapsed duplicates are merged so
    # evidence markers (pattern/arn/from_url) survive dedupe.
    kept: dict[tuple[str, str, str, str], MessagingSite] = {}
    for site in sites:
        key = (site.system, site.destination, site.role, site.env_var)
        if key in kept:
            kept[key].attrs.update(site.attrs)
        else:
            kept[key] = site
    return list(kept.values())


# --- per-language handlers ---------------------------------------------------

def _jvm(content: str, sites: list[MessagingSite]) -> None:
    for m in _JVM_KAFKA_LISTENER.finditer(content):
        args = m.group(1)
        pattern = _JVM_TOPIC_PATTERN.search(args)
        if pattern:
            _emit(sites, content, m.start(), "kafka", "consumes", "spring-kafka",
                  dynamic=True, attrs={"pattern": True}, raw=pattern.group(1).strip())
            continue
        values = _annotation_values(args, ("topics",))
        if not values:
            _emit(sites, content, m.start(), "kafka", "consumes", "spring-kafka",
                  dynamic=True, raw=args.strip())
            continue
        for value in values:
            _emit(sites, content, m.start(), "kafka", "consumes", "spring-kafka",
                  arg=value)

    for m in _JVM_KAFKA_TEMPLATE_SEND.finditer(content):
        _emit(sites, content, m.start(), "kafka", "produces", "spring-kafka",
              arg=m.group(1))
    for m in _JVM_PRODUCER_RECORD.finditer(content):
        _emit(sites, content, m.start(), "kafka", "produces", "kafka-clients",
              arg=m.group(1))
    for m in _JVM_SUBSCRIBE.finditer(content):
        _emit_from_window(sites, content, m.start(), "kafka", "consumes",
                          "kafka-clients", m.group(1))

    # Bare `.to(` / `.stream(` are too generic without a Streams topology in
    # the file; the type names are the gate.
    if "StreamsBuilder" in content or "KStream" in content:
        for m in _JVM_STREAMS_STREAM.finditer(content):
            _emit(sites, content, m.start(), "kafka", "consumes", "kafka-streams",
                  arg=m.group(1))
        for m in _JVM_STREAMS_TO.finditer(content):
            _emit(sites, content, m.start(), "kafka", "produces", "kafka-streams",
                  arg=m.group(1))
        for m in _JVM_STREAMS_THROUGH.finditer(content):
            # An intermediate topic is written and read back by the topology.
            for role in ("produces", "consumes"):
                _emit(sites, content, m.start(), "kafka", role, "kafka-streams",
                      arg=m.group(1))

    for m in _JVM_SQS_LISTENER.finditer(content):
        values = _annotation_values(m.group(1), ("value", "queueNames", "queues"))
        if not values:
            _emit(sites, content, m.start(), "sqs", "consumes", "spring-cloud-aws",
                  dynamic=True, raw=m.group(1).strip())
            continue
        for value in values:
            _emit(sites, content, m.start(), "sqs", "consumes", "spring-cloud-aws",
                  arg=value, queue_ref=True)
    for m in _JVM_SQS_TEMPLATE.finditer(content):
        _emit(sites, content, m.start(), "sqs", "produces", "spring-cloud-aws",
              arg=m.group(1), queue_ref=True)
    for m in _JVM_SQS_BUILDER.finditer(content):
        role = "produces" if m.group(1) == "Send" else "consumes"
        _emit(sites, content, m.start(), "sqs", role, "aws-sdk-java",
              arg=m.group(2), queue_ref=True)
    for m in _JVM_SNS_BUILDER.finditer(content):
        _emit(sites, content, m.start(), "sns", "produces", "aws-sdk-java",
              arg=m.group(1), queue_ref=True)


def _js_value(sites: list[MessagingSite], content: str, pos: int, system: str,
              role: str, framework: str, value: str, queue_ref: bool = False) -> None:
    value = value.strip()
    if value.startswith("["):
        _emit_elements(sites, content, pos, system, role, framework,
                       value.strip("[]"), queue_ref=queue_ref)
    else:
        _emit(sites, content, pos, system, role, framework, arg=value,
              queue_ref=queue_ref)


def _node(content: str, sites: list[MessagingSite]) -> None:
    for m in _NODE_KAFKAJS_SEND.finditer(content):
        window = content[m.start():m.start() + 400]
        key = _JS_TOPIC_KEY.search(window)
        if key:
            _js_value(sites, content, m.start(), "kafka", "produces", "kafkajs",
                      key.group(1))
        else:
            _emit(sites, content, m.start(), "kafka", "produces", "kafkajs",
                  dynamic=True, raw=window.split("\n", 1)[0])
    for m in _NODE_KAFKAJS_SENDBATCH.finditer(content):
        window = content[m.start():m.start() + 600]
        for key in _JS_TOPIC_KEY.finditer(window):
            _js_value(sites, content, m.start(), "kafka", "produces", "kafkajs",
                      key.group(1))

    for m in _NODE_SUBSCRIBE.finditer(content):
        window = content[m.end():m.end() + 400]
        head = window.lstrip()[:1]
        if head == "{":
            key = _JS_TOPICS_KEY.search(window)
            if key:
                _js_value(sites, content, m.start(), "kafka", "consumes",
                          "kafkajs", key.group(1))
        elif head == "[":
            inner = window.split("]", 1)[0].lstrip().lstrip("[")
            _emit_elements(sites, content, m.start(), "kafka", "consumes",
                           "node-rdkafka", inner)
        else:
            arg = re.split(r"[,)\n]", window, 1)[0]
            if arg.strip():
                _emit(sites, content, m.start(), "kafka", "consumes",
                      "node-rdkafka", arg=arg)
    for m in _NODE_RDKAFKA_PRODUCE.finditer(content):
        _emit(sites, content, m.start(), "kafka", "produces", "node-rdkafka",
              arg=m.group(1))

    for m in _NODE_NEST_PATTERN.finditer(content):
        if m.group(1).strip():
            _emit(sites, content, m.start(), "kafka", "consumes",
                  "nestjs-microservices", arg=m.group(1))
    # `client.send(` alone is any RPC client; require a Nest transport marker.
    if ("@nestjs/microservices" in content or "ClientProxy" in content
            or "ClientKafka" in content):
        for m in _NODE_NEST_EMIT.finditer(content):
            _emit(sites, content, m.start(), "kafka", "produces",
                  "nestjs-microservices", arg=m.group(1))

    for m in _NODE_V3_CMD.finditer(content):
        window = content[m.start():m.start() + 400]
        if m.group(1) == "Publish":
            key = _JS_TOPIC_ARN_KEY.search(window)
            if key:
                _emit(sites, content, m.start(), "sns", "produces",
                      "aws-sdk-js-v3", arg=key.group(1), queue_ref=True)
            continue
        role = "produces" if m.group(1) == "SendMessage" else "consumes"
        key = _JS_QUEUE_URL_KEY.search(window)
        if key:
            _emit(sites, content, m.start(), "sqs", role, "aws-sdk-js-v3",
                  arg=key.group(1), queue_ref=True)
        else:
            _emit(sites, content, m.start(), "sqs", role, "aws-sdk-js-v3",
                  dynamic=True, raw=window.split("\n", 1)[0])
    for m in _NODE_V2_SQS.finditer(content):
        window = content[m.start():m.start() + 400]
        key = _JS_QUEUE_URL_KEY.search(window)
        if key:
            role = "produces" if m.group(1) == "sendMessage" else "consumes"
            _emit(sites, content, m.start(), "sqs", role, "aws-sdk-js",
                  arg=key.group(1), queue_ref=True)
    for m in _NODE_V2_SNS.finditer(content):
        window = content[m.start():m.start() + 400]
        key = _JS_TOPIC_ARN_KEY.search(window)
        if key:
            _emit(sites, content, m.start(), "sns", "produces", "aws-sdk-js",
                  arg=key.group(1), queue_ref=True)


def _go(content: str, sites: list[MessagingSite]) -> None:
    for m in _GO_SARAMA_PRODUCER_MSG.finditer(content):
        _emit(sites, content, m.start(), "kafka", "produces", "sarama",
              arg=m.group(1))
    if "sarama" in content:
        for m in _GO_CONSUME_PARTITION.finditer(content):
            _emit(sites, content, m.start(), "kafka", "consumes", "sarama",
                  arg=m.group(1))
        for m in _GO_GROUP_CONSUME.finditer(content):
            if m.group(1) is not None:
                _emit_elements(sites, content, m.start(), "kafka", "consumes",
                               "sarama", m.group(1))
            else:
                _emit(sites, content, m.start(), "kafka", "consumes", "sarama",
                      arg=m.group(2))

    for pattern, role in ((_GO_SEGMENTIO_READER, "consumes"),
                          (_GO_SEGMENTIO_WRITER, "produces")):
        for m in pattern.finditer(content):
            window = content[m.start():m.start() + 500]
            key = _GO_TOPIC_FIELD.search(window)
            if key:
                _emit(sites, content, m.start(), "kafka", role,
                      "segmentio-kafka-go", arg=key.group(1))
            else:
                # Reader/Writer without Topic uses GroupTopics or per-message
                # topics; still definitely a kafka site.
                _emit(sites, content, m.start(), "kafka", role,
                      "segmentio-kafka-go", dynamic=True,
                      raw=window.split("\n", 1)[0])

    for m in _GO_CONFLUENT_SUBSCRIBE.finditer(content):
        if m.group(1) is not None:
            _emit_elements(sites, content, m.start(), "kafka", "consumes",
                           "confluent-kafka-go", m.group(1))
        else:
            _emit(sites, content, m.start(), "kafka", "consumes",
                  "confluent-kafka-go", arg=m.group(2))
    # TopicPartition literals also appear in offset/assign code; only a file
    # that produces gets the produces reading.
    if ".Produce(" in content or "kafka.Message{" in content:
        for m in _GO_CONFLUENT_TOPICPART.finditer(content):
            _emit(sites, content, m.start(), "kafka", "produces",
                  "confluent-kafka-go", arg=m.group(1))

    for m in _GO_SQS_INPUT.finditer(content):
        window = content[m.start():m.start() + 400]
        key = _GO_QUEUE_URL_FIELD.search(window)
        role = "produces" if m.group(1) == "SendMessage" else "consumes"
        if key:
            _emit(sites, content, m.start(), "sqs", role, "aws-sdk-go",
                  arg=key.group(1), queue_ref=True)
        else:
            _emit(sites, content, m.start(), "sqs", role, "aws-sdk-go",
                  dynamic=True, raw=window.split("\n", 1)[0])
    for m in _GO_SNS_PUBLISH.finditer(content):
        window = content[m.start():m.start() + 400]
        key = _GO_TOPIC_ARN_FIELD.search(window)
        if key:
            _emit(sites, content, m.start(), "sns", "produces", "aws-sdk-go",
                  arg=key.group(1), queue_ref=True)


def _python(content: str, sites: list[MessagingSite]) -> None:
    confluent = "confluent_kafka" in content
    for m in _PY_PRODUCER_SEND.finditer(content):
        method = m.group(1).lower()
        framework = {"send_and_wait": "aiokafka",
                     "produce": "confluent-kafka"}.get(method, "kafka-python")
        _emit(sites, content, m.start(), "kafka", "produces", framework,
              arg=m.group(2))

    for m in _PY_KAFKA_CONSUMER.finditer(content):
        for part in (p.strip() for p in m.group(1).split(",")):
            if "=" in part and not part.startswith(("'", '"')):
                break  # kwargs begin; positional topic args are over
            if part:
                _emit(sites, content, m.start(), "kafka", "consumes",
                      "kafka-python", arg=part)
    for m in _PY_SUBSCRIBE.finditer(content):
        window = re.sub(r"^\s*topics\s*=\s*", "", m.group(1))
        framework = "confluent-kafka" if confluent else "kafka-python"
        if window.lstrip().startswith(("[", "(")):
            _emit_elements(sites, content, m.start(), "kafka", "consumes",
                           framework, window.strip().strip("[]()"))
        else:
            _emit_from_window(sites, content, m.start(), "kafka", "consumes",
                              framework, window)

    for m in _PY_FAUST_TOPIC.finditer(content):
        _emit(sites, content, m.start(), "kafka", "consumes", "faust",
              arg=m.group(1), attrs={"faust_topic": True})
    for m in _PY_FAUST_AGENT.finditer(content):
        if m.group(1).strip():
            _emit(sites, content, m.start(), "kafka", "consumes", "faust",
                  arg=m.group(1))

    for m in _PY_BOTO3_SQS.finditer(content):
        key = _PY_QUEUE_URL_KW.search(m.group(2))
        if key:
            role = "produces" if m.group(1) == "send_message" else "consumes"
            _emit(sites, content, m.start(), "sqs", role, "boto3",
                  arg=key.group(1), queue_ref=True)
    for m in _PY_BOTO3_GET_QUEUE.finditer(content):
        # Direction is unknowable from a lookup; produces is the canonical
        # boto3 usage, and the attr lets the linker discount it.
        _emit(sites, content, m.start(), "sqs", "produces", "boto3",
              arg=m.group(1), attrs={"lookup": True})
    for m in _PY_BOTO3_SNS.finditer(content):
        key = _PY_TOPIC_ARN_KW.search(m.group(1))
        if key:
            _emit(sites, content, m.start(), "sns", "produces", "boto3",
                  arg=key.group(1), queue_ref=True)


def _csharp(content: str, sites: list[MessagingSite]) -> None:
    for m in _CS_PRODUCE.finditer(content):
        _emit(sites, content, m.start(), "kafka", "produces",
              "confluent-kafka-dotnet", arg=m.group(1))
    for m in _CS_SUBSCRIBE.finditer(content):
        _emit_from_window(sites, content, m.start(), "kafka", "consumes",
                          "confluent-kafka-dotnet", m.group(1))

    for m in _CS_AWS_REQ.finditer(content):
        kind, ctor_arg, brace = m.group(1), m.group(2), m.group(3)
        system = "sns" if kind == "Publish" else "sqs"
        role = "consumes" if kind == "ReceiveMessage" else "produces"
        if brace:
            window = content[m.start():m.start() + 400]
            key = (_CS_TOPIC_ARN_INIT if system == "sns"
                   else _CS_QUEUE_URL_INIT).search(window)
            if key:
                _emit(sites, content, m.start(), system, role, "aws-sdk-net",
                      arg=key.group(1), queue_ref=True)
            else:
                _emit(sites, content, m.start(), system, role, "aws-sdk-net",
                      dynamic=True, raw=window.split("\n", 1)[0])
        elif ctor_arg and ctor_arg.strip():
            _emit(sites, content, m.start(), system, role, "aws-sdk-net",
                  arg=ctor_arg, queue_ref=True)
    for m in _CS_SQS_SEND_ASYNC.finditer(content):
        if m.group(1).strip().startswith("new"):
            continue  # the request-object patterns above already cover it
        _emit(sites, content, m.start(), "sqs", "produces", "aws-sdk-net",
              arg=m.group(1), queue_ref=True)


def _binder_name(value: str) -> str:
    low = value.strip().lower()
    if "kafka" in low or low == "kstream":
        return "kafka"
    if "rabbit" in low:
        return "rabbit"
    return ""


def extract_stream_bindings(flat_config: dict) -> list[StreamBinding]:
    """Spring Cloud Stream bindings from flattened dotted config keys.

    Direction comes only from the ``-in-`` / ``-out-`` function-binding naming
    convention; anything else is skipped rather than guessed (``group``
    presence is not a reliable direction signal).
    """
    if not isinstance(flat_config, dict):
        return []

    binder_by_binding: dict[str, str] = {}
    default_binder = ""
    for key, value in flat_config.items():
        if not isinstance(key, str):
            continue
        if key in ("spring.cloud.stream.default-binder",
                   "spring.cloud.stream.defaultBinder"):
            if isinstance(value, str):
                default_binder = _binder_name(value)
            continue
        m = _SCS_BINDER.match(key)
        if m and isinstance(value, str):
            binder_by_binding[m.group(1)] = _binder_name(value)
            continue
        m = _SCS_SCOPED.match(key)
        if m:
            binder_by_binding.setdefault(m.group(2), m.group(1))

    bindings: list[StreamBinding] = []
    seen: set[tuple[str, str, str]] = set()
    for key, value in flat_config.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
            continue
        if key in _SPRING_KAFKA_DEFAULT_TOPIC:
            if "${" not in value:
                bindings.append(StreamBinding(
                    binding_name="spring.kafka.template.default-topic",
                    direction="produces", destination=value.strip(),
                    binder="kafka"))
            continue
        m = _SCS_DESTINATION.match(key)
        if not m:
            continue
        name = m.group(1)
        has_in, has_out = "-in-" in name, "-out-" in name
        if has_in == has_out:  # neither, or (nonsensically) both
            continue
        direction = "consumes" if has_in else "produces"
        binder = binder_by_binding.get(name, default_binder)
        # Consumers may list several comma-separated destinations.
        for dest in (d.strip() for d in value.split(",")):
            if not dest or "${" in dest:
                continue
            dedupe = (name, direction, dest)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            bindings.append(StreamBinding(binding_name=name, direction=direction,
                                          destination=dest, binder=binder))
    return bindings
