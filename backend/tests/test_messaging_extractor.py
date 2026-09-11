"""Messaging producer/consumer sites."""

from evigraph.services.messaging_extractor import (
    MessagingSite, extract_messaging_sites, extract_stream_bindings,
)


def find(results: list[MessagingSite], **kw) -> list[MessagingSite]:
    return [s for s in results if all(getattr(s, k) == v for k, v in kw.items())]


class TestKafkaJvm:
    def test_kafka_listener_forms(self):
        content = '''\
@Service
public class OrderListener {
    @KafkaListener(topics = "orders", groupId = "billing")
    public void onOrder(ConsumerRecord<String, String> rec) {}

    @KafkaListener(
        topics = {"refunds", "chargebacks"},
        groupId = "billing"
    )
    public void onRefund(String payload) {}

    @KafkaListener(topicPattern = "audit-.*")
    public void onAudit(String payload) {}
}
'''
        results = extract_messaging_sites(content, "java")
        orders = find(results, destination="orders")[0]
        assert (orders.system, orders.role, orders.framework) == \
            ("kafka", "consumes", "spring-kafka")
        assert orders.line == 3
        assert {s.destination for s in find(results, role="consumes", dynamic=False)} \
            == {"orders", "refunds", "chargebacks"}
        pattern = find(results, dynamic=True)[0]
        assert pattern.destination == "" and pattern.attrs.get("pattern") is True

    def test_kafka_template_send(self):
        content = '''\
kafkaTemplate.send("order-shipped", order.getId(), payload);
orderKafkaTemplate.send("audit", event);
kafkaTemplate.send(topicName, payload);
kafkaTemplate.send(System.getenv("ORDERS_TOPIC"), payload);
producer.send(new ProducerRecord<>("payments", key, value));
'''
        results = extract_messaging_sites(content, "java")
        assert {s.destination for s in find(results, role="produces", dynamic=False,
                                            env_var="")} == \
            {"order-shipped", "audit", "payments"}
        assert find(results, destination="payments")[0].framework == "kafka-clients"
        assert len(find(results, dynamic=True)) == 1
        assert find(results, env_var="ORDERS_TOPIC")[0].destination == ""

    def test_kafka_streams_topology(self):
        content = '''\
StreamsBuilder builder = new StreamsBuilder();
KStream<String, Order> orders = builder.stream("orders-raw");
orders.filter((k, v) -> v.isValid()).to("orders-enriched");
orders.through("orders-repartition").groupByKey();
'''
        results = extract_messaging_sites(content, "java")
        assert find(results, destination="orders-raw")[0].role == "consumes"
        assert find(results, destination="orders-enriched")[0].role == "produces"
        # An intermediate topic is both written and read back by the topology.
        assert {s.role for s in find(results, destination="orders-repartition")} \
            == {"produces", "consumes"}
        assert all(s.framework == "kafka-streams" for s in results)

    def test_consumer_subscribe(self):
        content = '''\
consumer.subscribe(List.of("orders", "refunds"));
kafkaConsumer.subscribe(Arrays.asList(inventoryTopics));
consumer.subscribe(Collections.singletonList("audit"));
consumer.subscribe(Pattern.compile("orders-.*"));
'''
        results = extract_messaging_sites(content, "java")
        assert {s.destination for s in find(results, dynamic=False)} == \
            {"orders", "refunds", "audit"}
        dynamics = find(results, dynamic=True)
        assert any(s.attrs.get("pattern") for s in dynamics)


class TestSqsSnsJvm:
    def test_sqs_listener_and_template(self):
        content = '''\
@SqsListener("order-events-queue")
public void handle(OrderEvent e) {}

@SqsListener(value = "billing-queue", maxConcurrentMessages = "5")
public void handleBilling(Invoice i) {}

sqsTemplate.send("notify-queue", MessageBuilder.withPayload(p).build());
'''
        results = extract_messaging_sites(content, "java")
        assert {s.destination for s in find(results, system="sqs", role="consumes")} \
            == {"order-events-queue", "billing-queue"}
        produced = find(results, system="sqs", role="produces")[0]
        assert produced.destination == "notify-queue"
        assert produced.framework == "spring-cloud-aws"

    def test_sdk_builders_url_and_arn(self):
        content = '''\
SendMessageRequest req = SendMessageRequest.builder()
        .queueUrl("https://sqs.us-east-1.amazonaws.com/123456789012/orders-queue")
        .messageBody(body)
        .build();
ReceiveMessageRequest poll = ReceiveMessageRequest.builder()
        .queueUrl(queueUrl)
        .maxNumberOfMessages(10)
        .build();
PublishRequest pub = PublishRequest.builder()
        .topicArn("arn:aws:sns:us-east-1:123456789012:order-events")
        .message(json)
        .build();
'''
        results = extract_messaging_sites(content, "java")
        sent = find(results, system="sqs", role="produces")[0]
        assert sent.destination == "orders-queue"
        assert sent.attrs.get("from_url") is True
        assert find(results, system="sqs", role="consumes")[0].dynamic is True
        topic = find(results, system="sns")[0]
        assert (topic.destination, topic.role) == ("order-events", "produces")
        assert topic.attrs.get("arn") is True


class TestKafkaNode:
    def test_kafkajs_send_and_batch(self):
        content = '''\
const producer = kafka.producer();
await producer.send({
  topic: 'user-signup',
  messages: [{ value: JSON.stringify(user) }],
});
await producer.sendBatch({
  topicMessages: [
    { topic: 'audit-log', messages: auditMsgs },
    { topic: 'metrics', messages: metricMsgs },
  ],
});
await producer.send({ topic: process.env.EVENTS_TOPIC, messages: batch });
'''
        results = extract_messaging_sites(content, "javascript")
        assert {s.destination for s in find(results, role="produces", dynamic=False,
                                            env_var="")} == \
            {"user-signup", "audit-log", "metrics"}
        assert find(results, env_var="EVENTS_TOPIC")[0].framework == "kafkajs"

    def test_subscribe_and_rdkafka(self):
        content = '''\
await consumer.subscribe({ topic: 'user-signup', fromBeginning: true });
await consumer.subscribe({ topics: ['payments', 'refunds'] });
await consumer.subscribe({ topics: [/^orders-.*/] });
rdProducer.produce('telemetry', null, Buffer.from(payload), key);
rdConsumer.subscribe(['telemetry']);
'''
        results = extract_messaging_sites(content, "typescript")
        assert {s.destination for s in find(results, role="consumes", dynamic=False)} \
            == {"user-signup", "payments", "refunds", "telemetry"}
        assert find(results, dynamic=True)[0].attrs.get("pattern") is True
        produced = find(results, role="produces")[0]
        assert (produced.destination, produced.framework) == \
            ("telemetry", "node-rdkafka")

    def test_nestjs_microservices(self):
        content = '''\
import { MessagePattern, EventPattern, ClientProxy } from '@nestjs/microservices';

@Controller()
export class OrdersController {
  @MessagePattern('order.created')
  handleCreated(@Payload() data: OrderDto) {}

  @EventPattern('order.shipped')
  handleShipped(data: any) {}

  notify() {
    this.client.emit('order.created', this.order);
    this.client.send('billing.charge', payload);
  }
}
'''
        results = extract_messaging_sites(content, "typescript")
        assert {s.destination for s in find(results, role="consumes")} == \
            {"order.created", "order.shipped"}
        assert {s.destination for s in find(results, role="produces")} == \
            {"order.created", "billing.charge"}
        assert all(s.framework == "nestjs-microservices" for s in results)

    def test_client_send_needs_nest_marker(self):
        # Without a Nest transport marker, client.send is any RPC client.
        content = "this.client.send('order.created', payload);\n"
        assert extract_messaging_sites(content, "typescript") == []


class TestAwsNode:
    def test_sdk_v3_commands(self):
        content = '''\
await sqsClient.send(new SendMessageCommand({
  QueueUrl: 'https://sqs.us-west-2.amazonaws.com/123456789012/billing-queue',
  MessageBody: JSON.stringify(invoice),
}));
const out = await sqsClient.send(new ReceiveMessageCommand({
  QueueUrl: process.env.BILLING_QUEUE_URL,
  WaitTimeSeconds: 20,
}));
await snsClient.send(new PublishCommand({
  TopicArn: 'arn:aws:sns:us-east-1:123456789012:invoice-events',
  Message: msg,
}));
'''
        results = extract_messaging_sites(content, "javascript")
        sent = find(results, system="sqs", role="produces")[0]
        assert (sent.destination, sent.attrs.get("from_url")) == ("billing-queue", True)
        assert find(results, system="sqs", role="consumes")[0].env_var == \
            "BILLING_QUEUE_URL"
        topic = find(results, system="sns")[0]
        assert (topic.destination, topic.attrs.get("arn")) == ("invoice-events", True)

    def test_sdk_v2_calls(self):
        content = '''\
sqs.sendMessage({ QueueUrl: queueUrl, MessageBody: body }, callback);
sns.publish({ TopicArn: 'arn:aws:sns:us-east-1:123456789012:alerts', Message: m })
  .promise();
'''
        results = extract_messaging_sites(content, "javascript")
        assert find(results, system="sqs")[0].dynamic is True
        assert find(results, system="sns")[0].destination == "alerts"


class TestKafkaGo:
    def test_sarama(self):
        content = '''\
import "github.com/IBM/sarama"

msg := &sarama.ProducerMessage{
	Topic: "order-events",
	Value: sarama.StringEncoder(payload),
}
pc, err := consumer.ConsumePartition("order-events", 0, sarama.OffsetNewest)
if err := group.Consume(ctx, []string{"orders", "refunds"}, &handler); err != nil {
	return err
}
'''
        results = extract_messaging_sites(content, "go")
        assert find(results, role="produces")[0].destination == "order-events"
        assert {s.destination for s in find(results, role="consumes")} == \
            {"order-events", "orders", "refunds"}
        assert all(s.framework == "sarama" for s in results)

    def test_segmentio(self):
        content = '''\
r := kafka.NewReader(kafka.ReaderConfig{
	Brokers: []string{"kafka:9092"},
	GroupID: "shipping",
	Topic:   "order-events",
})
w := &kafka.Writer{
	Addr:  kafka.TCP("kafka:9092"),
	Topic: os.Getenv("SHIPMENT_TOPIC"),
}
'''
        results = extract_messaging_sites(content, "go")
        reader = find(results, role="consumes")[0]
        assert (reader.destination, reader.framework) == \
            ("order-events", "segmentio-kafka-go")
        assert find(results, role="produces")[0].env_var == "SHIPMENT_TOPIC"

    def test_confluent_dynamic_topic_pointer(self):
        content = '''\
import "github.com/confluentinc/confluent-kafka-go/v2/kafka"

c.SubscribeTopics([]string{"inventory-updates"}, nil)
topic := "unused-hint"
p.Produce(&kafka.Message{
	TopicPartition: kafka.TopicPartition{Topic: &topic, Partition: kafka.PartitionAny},
	Value:          payload,
}, nil)
'''
        results = extract_messaging_sites(content, "go")
        assert find(results, role="consumes")[0].destination == "inventory-updates"
        # &topic is a pointer to a variable: never chased, always dynamic.
        produced = find(results, role="produces")[0]
        assert (produced.destination, produced.dynamic) == ("", True)


class TestSqsSnsGo:
    def test_sqs_inputs_and_sns_publish(self):
        content = '''\
out, err := client.SendMessage(ctx, &sqs.SendMessageInput{
	QueueUrl:    aws.String("https://sqs.us-east-1.amazonaws.com/123456789012/orders-queue"),
	MessageBody: aws.String(body),
})
msgs, err := client.ReceiveMessage(ctx, &sqs.ReceiveMessageInput{
	QueueUrl:            queueURL,
	MaxNumberOfMessages: 10,
})
_, err = snsClient.Publish(ctx, &sns.PublishInput{
	TopicArn: aws.String("arn:aws:sns:us-east-1:123456789012:order-events"),
	Message:  aws.String(m),
})
'''
        results = extract_messaging_sites(content, "go")
        sent = find(results, system="sqs", role="produces")[0]
        assert (sent.destination, sent.attrs.get("from_url")) == ("orders-queue", True)
        assert find(results, system="sqs", role="consumes")[0].dynamic is True
        assert find(results, system="sns")[0].destination == "order-events"


class TestKafkaPython:
    def test_producers(self):
        content = '''\
from confluent_kafka import Producer

producer = KafkaProducer(bootstrap_servers="kafka:9092")
producer.send("page-views", value=payload)
producer.send(topic="clicks", value=payload)
click_producer.produce("clickstream", key=uid, value=evt)
await aio_producer.send_and_wait("email-requests", msg)
'''
        results = extract_messaging_sites(content, "python")
        assert {s.destination for s in results} == \
            {"page-views", "clicks", "clickstream", "email-requests"}
        assert find(results, destination="clickstream")[0].framework == \
            "confluent-kafka"
        assert find(results, destination="email-requests")[0].framework == "aiokafka"
        assert all(s.role == "produces" for s in results)

    def test_consumers(self):
        content = '''\
consumer = KafkaConsumer("page-views", "clicks", bootstrap_servers="kafka:9092")
consumer.subscribe(["orders", "payments"])
consumer.subscribe(topics=["orders"])
consumer.subscribe(pattern="^orders-.*")
'''
        results = extract_messaging_sites(content, "python")
        assert {s.destination for s in find(results, dynamic=False)} == \
            {"page-views", "clicks", "orders", "payments"}
        assert find(results, dynamic=True)[0].attrs.get("pattern") is True

    def test_faust(self):
        content = '''\
import faust

app = faust.App("analytics", broker="kafka://kafka:9092")
page_view_topic = app.topic("page-views", value_type=PageView)


@app.agent(page_view_topic)
async def process(views):
    async for view in views:
        await view.save()
'''
        results = extract_messaging_sites(content, "python")
        declared = find(results, destination="page-views")[0]
        assert (declared.role, declared.framework) == ("consumes", "faust")
        assert declared.attrs.get("faust_topic") is True
        assert find(results, dynamic=True)[0].destination == ""


class TestAwsPython:
    def test_boto3_sqs_sns(self):
        content = '''\
sqs = boto3.client("sqs")
sqs.send_message(
    QueueUrl="https://sqs.us-east-1.amazonaws.com/123456789012/orders-queue",
    MessageBody=body,
)
messages = sqs.receive_message(QueueUrl=os.environ["ORDERS_QUEUE_URL"], WaitTimeSeconds=20)
queue = sqs_resource.get_queue_by_name(QueueName="dead-letter")
sns.publish(TopicArn="arn:aws:sns:us-east-1:123456789012:payment-alerts", Message=alert)
'''
        results = extract_messaging_sites(content, "python")
        sent = find(results, system="sqs", role="produces", destination="orders-queue")
        assert sent[0].attrs.get("from_url") is True
        assert find(results, role="consumes")[0].env_var == "ORDERS_QUEUE_URL"
        lookup = find(results, destination="dead-letter")[0]
        assert lookup.attrs.get("lookup") is True
        topic = find(results, system="sns")[0]
        assert (topic.destination, topic.attrs.get("arn")) == ("payment-alerts", True)


class TestKafkaCsharp:
    def test_confluent_produce_subscribe(self):
        content = '''\
using Confluent.Kafka;

await producer.ProduceAsync("checkout-events", new Message<Null, string> { Value = json });
producer.Produce("audit", new Message<Null, string> { Value = line });
consumer.Subscribe("checkout-events");
consumer.Subscribe(new[] { "inventory", "restock" });
'''
        results = extract_messaging_sites(content, "c#")
        assert {s.destination for s in find(results, role="produces")} == \
            {"checkout-events", "audit"}
        assert {s.destination for s in find(results, role="consumes")} == \
            {"checkout-events", "inventory", "restock"}
        assert all(s.framework == "confluent-kafka-dotnet" for s in results)


class TestAwsCsharp:
    def test_aws_sdk_requests(self):
        content = '''\
var send = new SendMessageRequest
{
    QueueUrl = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-queue",
    MessageBody = body,
};
await sqsClient.SendMessageAsync(queueUrl, body);
var poll = new ReceiveMessageRequest
{
    QueueUrl = Environment.GetEnvironmentVariable("ORDERS_QUEUE_URL"),
    MaxNumberOfMessages = 10,
};
var pub = new PublishRequest { TopicArn = "arn:aws:sns:us-east-1:123456789012:order-events", Message = json };
'''
        results = extract_messaging_sites(content, "csharp")
        assert find(results, system="sqs", role="produces", dynamic=False)[0] \
            .destination == "orders-queue"
        assert len(find(results, system="sqs", role="produces", dynamic=True)) == 1
        assert find(results, system="sqs", role="consumes")[0].env_var == \
            "ORDERS_QUEUE_URL"
        topic = find(results, system="sns")[0]
        assert (topic.destination, topic.attrs.get("arn")) == ("order-events", True)


class TestStreamBindings:
    def test_directions_binders_and_skips(self):
        flat = {
            "spring.cloud.stream.bindings.processOrder-in-0.destination": "orders",
            "spring.cloud.stream.bindings.processOrder-in-0.group": "billing",
            "spring.cloud.stream.bindings.emitShipped-out-0.destination": "shipped",
            "spring.cloud.stream.bindings.emitShipped-out-0.binder": "kafka",
            "spring.cloud.stream.kafka.bindings.processOrder-in-0.consumer.ackMode": "MANUAL",
            "spring.cloud.stream.bindings.mystery.destination": "who-knows",
        }
        bindings = extract_stream_bindings(flat)
        inbound = [b for b in bindings if b.binding_name == "processOrder-in-0"][0]
        assert (inbound.direction, inbound.destination, inbound.binder) == \
            ("consumes", "orders", "kafka")
        outbound = [b for b in bindings if b.binding_name == "emitShipped-out-0"][0]
        assert (outbound.direction, outbound.binder) == ("produces", "kafka")
        # No -in-/-out- marker means direction would be a guess: skipped.
        assert not [b for b in bindings if b.destination == "who-knows"]

    def test_default_binder_comma_list_and_default_topic(self):
        flat = {
            "spring.cloud.stream.default-binder": "rabbit",
            "spring.cloud.stream.bindings.audit-in-0.destination": "orders,payments",
            "spring.cloud.stream.bindings.skip-in-0.destination": "${TOPIC}",
            "spring.kafka.template.default-topic": "outbound-events",
        }
        bindings = extract_stream_bindings(flat)
        audit = [b for b in bindings if b.binding_name == "audit-in-0"]
        assert {b.destination for b in audit} == {"orders", "payments"}
        assert all(b.binder == "rabbit" for b in audit)
        assert not [b for b in bindings if "${" in b.destination]
        default = [b for b in bindings
                   if b.binding_name == "spring.kafka.template.default-topic"][0]
        assert (default.direction, default.destination, default.binder) == \
            ("produces", "outbound-events", "kafka")


class TestRobustness:
    def test_malformed_input_does_not_raise(self):
        broken = '@KafkaListener(topics = {"a", \n producer.send( \x00\x01'
        assert isinstance(extract_messaging_sites(broken, "java"), list)
        assert extract_messaging_sites("", "java") == []
        assert extract_messaging_sites(None, "python") == []
        assert extract_messaging_sites("producer.send('t')", None) == []
        assert extract_messaging_sites("producer.send('t')", "ruby") == []
        assert extract_stream_bindings(None) == []
        assert extract_stream_bindings(
            {"spring.cloud.stream.bindings.x-in-0.destination": 42}) == []

    def test_plain_send_is_not_messaging(self):
        assert extract_messaging_sites("emailService.send(message);", "java") == []
        assert extract_messaging_sites("composer.send('welcome')", "python") == []
        assert extract_messaging_sites("res.send(JSON.stringify(x));", "javascript") \
            == []

    def test_commented_send_still_matches(self):
        # No comment stripping by design: a commented-out producer is accepted
        # noise, cheaper than an AST pass on every file.
        content = '// kafkaTemplate.send("legacy-topic", msg);\n'
        results = extract_messaging_sites(content, "java")
        assert [s.destination for s in results] == ["legacy-topic"]

    def test_dedupe_by_system_destination_role_env(self):
        content = '''\
kafkaTemplate.send("orders", a);
kafkaTemplate.send("orders", b);
'''
        results = extract_messaging_sites(content, "java")
        assert len(results) == 1
        assert results[0].line == 1
