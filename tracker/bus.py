"""Kafka transport: one consumer for the data and command topics, one producer for the output topic."""
import logging

from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError

log = logging.getLogger("bus")


class KafkaBus:
    def __init__(self, kafka_cfg):
        self.servers = kafka_cfg["servers"]
        self.data_topic = kafka_cfg["data_topic"]
        self.command_topic = kafka_cfg["command_topic"]
        self.output_topic = kafka_cfg["output_topic"]
        self.consumer = None
        self.producer = None

    def connect(self, stop_event, retry_every=2.0):
        """Connect, retrying until it works or stop_event is set. :return: whether connected"""
        while not stop_event.is_set():
            try:
                # No consumer group: every tracker instance sees every message, starting from now
                self.consumer = KafkaConsumer(self.data_topic, self.command_topic, bootstrap_servers=self.servers,
                                              auto_offset_reset="latest", enable_auto_commit=False)
                self.producer = KafkaProducer(bootstrap_servers=self.servers)
                log.info(f"Connected to Kafka at {', '.join(self.servers)}")
                return True
            # kafka-python 2.3 raises a bare ValueError ("Invalid file object") when the connection is refused
            except (KafkaError, OSError, ValueError) as error:
                if self.consumer is not None:
                    self.consumer.close()
                    self.consumer = None
                log.warning(f"Can't connect to Kafka at {', '.join(self.servers)} ({error}); "
                            f"retrying in {retry_every:.0f}s")
                stop_event.wait(retry_every)
        return False

    def poll(self):
        """:return: [(topic, key, value)] for every message received since the last poll, from all partitions"""
        batches = self.consumer.poll(timeout_ms=0, max_records=2000)
        records = [record for batch in batches.values() for record in batch]
        records.sort(key=lambda record: record.timestamp)
        return [(record.topic, record.key, record.value) for record in records]

    def send(self, key, value):
        try:
            self.producer.send(self.output_topic, key=key, value=value)
        except KafkaError as error:
            log.warning(f"Couldn't publish to {self.output_topic}: {error}")

    def close(self):
        if self.producer:
            self.producer.flush(timeout=5)
            self.producer.close(timeout=5)
        if self.consumer:
            self.consumer.close()
