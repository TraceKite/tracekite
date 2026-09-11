"""AsyncAPI channels + Avro subjects.

The load-bearing assertion set is the 2.x verb inversion: `publish` means the
app CONSUMES and `subscribe` means it PRODUCES. Get that backwards and every
declared topic edge in the graph points the wrong way.
"""

from tracekite.parsers.asyncapi_parser import (
    is_asyncapi_file, is_avro_schema_file, parse_asyncapi, parse_avro_schema,
)

V2_DOC = """\
asyncapi: '2.6.0'
info:
  title: Orders Service
  version: 1.4.0
servers:
  production:
    url: kafka.petclinic.internal:9092
    protocol: kafka
channels:
  orders.created:
    description: Emitted after checkout commits an order.
    subscribe:
      operationId: publishOrderCreated
      message:
        $ref: '#/components/messages/OrderCreated'
  payments.completed:
    publish:
      operationId: onPaymentCompleted
      message:
        name: PaymentCompleted
  user/{userId}/notifications:
    parameters:
      userId:
        schema:
          type: string
    subscribe:
      operationId: notifyUser
components:
  messages:
    OrderCreated:
      payload:
        type: object
"""

V3_DOC = """\
asyncapi: 3.0.0
info:
  title: Notification Hub
  version: 2.0.0
servers:
  broker:
    host: kafka.petclinic.internal:9092
    protocol: kafka
channels:
  orderCreated:
    address: orders.created
    messages:
      event:
        payload:
          type: object
  deadLetters:
    address: orders.dlq
  userEvents:
    address: null
operations:
  onOrderCreated:
    action: receive
    channel:
      $ref: '#/channels/orderCreated'
  emitUserEvent:
    action: send
    channel:
      $ref: '#/channels/userEvents'
"""

JSON_DOC = ('{"asyncapi": "2.0.0", "info": {"title": "Ledger"},'
            ' "channels": {"ledger.entries": {"publish": {"operationId": "onEntry"}}}}')

AVRO_RECORD = """\
{
  "type": "record",
  "name": "OrderCreated",
  "namespace": "org.petclinic.orders",
  "fields": [
    {"name": "orderId", "type": "string"},
    {"name": "amountCents", "type": "long"}
  ]
}
"""

AVRO_UNION = ('["null", {"type": "record", "name": "Refund",'
              ' "namespace": "org.petclinic.payments", "fields": []}]')


def _by_channel(doc):
    return {op.channel: op for op in doc.operations}


class TestAsyncAPIv2:
    def test_identity(self):
        doc = parse_asyncapi("asyncapi.yaml", V2_DOC)
        assert (doc.title, doc.version) == ("Orders Service", "2.6.0")

    def test_subscribe_means_the_app_produces(self):
        op = _by_channel(parse_asyncapi("a.yaml", V2_DOC))["orders.created"]
        assert (op.action, op.address) == ("produces", "orders.created")

    def test_publish_means_the_app_consumes(self):
        op = _by_channel(parse_asyncapi("a.yaml", V2_DOC))["payments.completed"]
        assert op.action == "consumes"

    def test_server_protocol_reaches_every_operation(self):
        doc = parse_asyncapi("a.yaml", V2_DOC)
        assert {op.protocol for op in doc.operations} == {"kafka"}

    def test_parameterized_channel_keeps_braces_literally(self):
        op = _by_channel(parse_asyncapi("a.yaml", V2_DOC))["user/{userId}/notifications"]
        assert (op.address, op.action) == ("user/{userId}/notifications", "produces")

    def test_declared_channels_in_document_order(self):
        assert parse_asyncapi("a.yaml", V2_DOC).declared_channels == [
            "orders.created", "payments.completed", "user/{userId}/notifications",
        ]


class TestAsyncAPIv3:
    def test_receive_maps_to_consumes_with_resolved_address(self):
        doc = parse_asyncapi("asyncapi.yaml", V3_DOC)
        assert doc.version == "3.0.0"
        op = _by_channel(doc)["orderCreated"]
        assert (op.action, op.address, op.protocol) == \
            ("consumes", "orders.created", "kafka")

    def test_send_maps_to_produces_and_null_address_falls_back_to_key(self):
        op = _by_channel(parse_asyncapi("a.yaml", V3_DOC))["userEvents"]
        assert (op.action, op.address) == ("produces", "userEvents")

    def test_channel_without_operation_is_still_declared(self):
        doc = parse_asyncapi("a.yaml", V3_DOC)
        assert len(doc.operations) == 2
        assert doc.declared_channels == ["orders.created", "orders.dlq", "userEvents"]


class TestSniffAndJson:
    def test_json_document_parses(self):
        doc = parse_asyncapi("asyncapi.json", JSON_DOC)
        assert doc.title == "Ledger"
        [op] = doc.operations
        assert (op.address, op.action) == ("ledger.entries", "consumes")

    def test_sniff_by_name_or_content(self):
        assert is_asyncapi_file("docs/asyncapi-orders.yaml", "")
        assert is_asyncapi_file("streams.yml", V2_DOC)          # content signal
        assert is_asyncapi_file("api/asyncapi.json", JSON_DOC)

    def test_sniff_rejects_other_yaml(self):
        assert not is_asyncapi_file("deploy.yaml", "kind: Deployment\nspec: {}\n")


class TestProtocolHintsAndRefs:
    def test_v2_channel_bindings_supply_protocol_without_servers(self):
        doc = parse_asyncapi("b.yaml", (
            "asyncapi: '2.6.0'\n"
            "info: {title: Inventory Worker}\n"
            "channels:\n"
            "  inventory.restock:\n"
            "    bindings:\n"
            "      kafka: {topic: inventory.restock}\n"
            "    publish: {operationId: onRestock}\n"))
        [op] = doc.operations
        assert (op.address, op.action, op.protocol) == \
            ("inventory.restock", "consumes", "kafka")

    def test_v3_escaped_ref_and_operation_bindings(self):
        doc = parse_asyncapi("c.yaml", (
            "asyncapi: 3.0.0\n"
            "info: {title: Fan Out}\n"
            "channels:\n"
            "  user/{userId}/events:\n"
            "    address: null\n"
            "operations:\n"
            "  fanOut:\n"
            "    action: send\n"
            "    bindings: {sqs: {}}\n"
            "    channel:\n"
            "      $ref: '#/channels/user~1{userId}~1events'\n"))
        [op] = doc.operations          # ~1 unescapes to "/" per RFC 6901
        assert (op.channel, op.address) == \
            ("user/{userId}/events", "user/{userId}/events")
        assert (op.action, op.protocol) == ("produces", "sqs")


class TestAvroSchema:
    def test_record_identity(self):
        schema = parse_avro_schema("schemas/order_created.avsc", AVRO_RECORD)
        assert (schema.name, schema.namespace) == ("OrderCreated", "org.petclinic.orders")
        assert schema.full_name == "org.petclinic.orders.OrderCreated"
        assert schema.subject_hint == ""    # file name carries no -value/-key

    def test_registry_subject_hint_from_file_name(self):
        assert parse_avro_schema("schemas/orders-value.avsc",
                                 AVRO_RECORD).subject_hint == "orders-value"
        assert parse_avro_schema("payments-key.avsc",
                                 AVRO_RECORD).subject_hint == "payments-key"

    def test_union_takes_first_record(self):
        schema = parse_avro_schema("refund.avsc", AVRO_UNION)
        assert schema.full_name == "org.petclinic.payments.Refund"

    def test_non_record_returns_none(self):
        enum = '{"type": "enum", "name": "Color", "symbols": ["RED"]}'
        assert parse_avro_schema("color.avsc", enum) is None
        assert is_avro_schema_file("orders-value.avsc")

    def test_avro_edge_shapes(self):
        assert parse_avro_schema("x.avsc", "") is None
        assert parse_avro_schema("x.avsc", '{"type": "record", "fields": []}') is None
        # Avro fullname rule: a dotted name IS the fullname; namespace is ignored.
        dotted = '{"type": "record", "name": "com.acme.Evt", "namespace": "ignored"}'
        schema = parse_avro_schema("x.avsc", dotted)
        assert (schema.namespace, schema.name, schema.full_name) == \
            ("com.acme", "Evt", "com.acme.Evt")


class TestDefensiveness:
    def test_malformed_yaml_and_json_do_not_raise(self):
        assert parse_asyncapi("x.yaml", "asyncapi: [unclosed\n  ::junk") is None
        assert parse_avro_schema("x.avsc", '{"type": "record", oops') is None

    def test_empty_or_absent_body(self):
        assert parse_asyncapi("x.yaml", "") is None
        assert parse_asyncapi("x.yaml", None) is None
        assert not is_asyncapi_file("x.yaml", None)

    def test_valid_yaml_that_is_not_asyncapi(self):
        assert parse_asyncapi("deploy.yaml", "kind: Deployment\nspec: {}\n") is None
        assert parse_asyncapi("note.yaml", "just a scalar") is None

    def test_odd_channel_shapes_yield_empty_results(self):
        doc = parse_asyncapi("x.yaml", "asyncapi: '2.1.0'\nchannels: [not, a, map]\n")
        assert (doc.operations, doc.declared_channels) == ([], [])
        # A channel with a null body is still a declared address.
        doc = parse_asyncapi("x.yaml", "asyncapi: '2.1.0'\nchannels:\n  orders.x:\n")
        assert (doc.declared_channels, doc.operations) == (["orders.x"], [])

    def test_declines_rather_than_guessing(self):
        # Unknown action, non-dict operation, missing/refless channel, and
        # unrecognized protocols must all decline silently, never raise.
        doc = parse_asyncapi("x.yaml", (
            "asyncapi: 3.0.0\n"
            "info: {title: X}\n"
            "servers:\n"
            "  s: {protocol: mqtt}\n"
            "channels:\n"
            "  a: {address: t.a, bindings: {mqtt: {}}}\n"
            "operations:\n"
            "  bad1: {action: subscribe, channel: {$ref: '#/channels/a'}}\n"
            "  bad2: 7\n"
            "  bad3: {action: send}\n"
            "  bad4: {action: send, channel: {$ref: 'no-pointer'}}\n"
            "  good: {action: send, channel: {$ref: '#/channels/a'}}\n"))
        [op] = doc.operations
        assert (op.address, op.action, op.protocol) == ("t.a", "produces", "")
        # v2: a null verb body is still a declared operation.
        doc = parse_asyncapi("x.yaml", "asyncapi: '2.0.0'\nchannels:\n  q:\n    publish:\n")
        [op] = doc.operations
        assert (op.address, op.action, op.protocol) == ("q", "consumes", "")

    def test_tab_indented_json_uses_the_json_fallback(self):
        tabbed = '{\n\t"asyncapi": "2.0.0",\n\t"channels": {"t.x": {"subscribe": {}}}\n}'
        [op] = parse_asyncapi("c.json", tabbed).operations
        assert (op.address, op.action) == ("t.x", "produces")
