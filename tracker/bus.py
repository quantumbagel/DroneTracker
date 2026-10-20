"""Kafka transport: one consumer for the data and command topics, one producer for the output topic."""
import logging
import queue
import threading

from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError

log = logging.getLogger("bus")

SEND_QUEUE = 1000  # Outgoing messages buffered while the broker is unreachable; beyond this they are dropped


class KafkaBus:
    """
    Publishing happens on a background thread: KafkaProducer.send() blocks for up to a minute while it has no
    metadata for the output topic (broker down, or the topic missing), and the tracking loop must never stall.
    """

    def __init__(self, kafka_cfg):
        self.servers = kafka_cfg["servers"]
        self.data_topic = kafka_cfg["data_topic"]
        self.command_topic = kafka_cfg["command_topic"]
        self.output_topic = kafka_cfg["output_topic"]
        self.consumer = None
        self.producer = None
        self._outbox = queue.Queue(maxsize=SEND_QUEUE)
        self._sender = None
        self._dropped = 0

    def connect(self, stop_event, retry_every=2.0):
        """Connect, retrying until it works or stop_event is set. :return: whether connected"""
        while not stop_event.is_set():
            try:
                # No consumer group: every tracker instance sees every message, starting from now
                self.consumer = KafkaConsumer(self.data_topic, self.command_topic, bootstrap_servers=self.servers,
                                              auto_offset_reset="latest", enable_auto_commit=False)
                self.producer = KafkaProducer(bootstrap_servers=self.servers)
                log.info(f"Connected to Kafka at {', '.join(self.servers)}")
                self._sender = threading.Thread(target=self._send_loop, name="kafka-send", daemon=True)
                self._sender.start()
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
        """
        :return: [(topic, key, value, timestamp)] for every message received since the last poll, from all
         partitions, in time order. timestamp is the record's epoch seconds (normally when the sender produced it),
         or None if the record has none.
        """
        batches = self.consumer.poll(timeout_ms=0, max_records=2000)
        records = [record for batch in batches.values() for record in batch]
        records.sort(key=lambda record: record.timestamp)
        return [(record.topic, record.key, record.value, record.timestamp / 1000 if record.timestamp > 0 else None)
                for record in records]

    def send(self, key, value):
        """Queue a message for the output topic. Never blocks."""
        try:
            self._outbox.put_nowait((key, value))
        except queue.Full:
            self._dropped += 1
            if self._dropped == 1 or self._dropped % 100 == 0:
                log.warning(f"Kafka output backed up; dropped {self._dropped} message(s) for {self.output_topic}")

    def _send_loop(self):
        while True:
            item = self._outbox.get()
            if item is None:
                return
            try:
                self.producer.send(self.output_topic, key=item[0], value=item[1])
            except KafkaError as error:
                log.warning(f"Couldn't publish to {self.output_topic}: {error}")

    def close(self, timeout=5.0):
        if self._sender is not None:
            try:
                self._outbox.put(None, timeout=timeout)
            except queue.Full:
                pass
            self._sender.join(timeout)
        if self.producer:
            self.producer.flush(timeout=timeout)
            self.producer.close(timeout=timeout)
        if self.consumer:
            self.consumer.close()
