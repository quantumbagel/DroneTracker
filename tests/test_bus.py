import threading
from collections import namedtuple

from kafka.errors import NoBrokersAvailable

from tracker import bus as bus_module
from tracker.bus import KafkaBus

Record = namedtuple("Record", "topic key value timestamp")
KAFKA = {"servers": ["k:9092"], "data_topic": "data", "command_topic": "cmd", "output_topic": "out"}


class FakeConsumer:
    def __init__(self, *topics, **config):
        self.topics, self.config, self.closed = topics, config, False
        self.batches = {}

    def poll(self, timeout_ms, max_records):
        batches, self.batches = self.batches, {}
        return batches

    def close(self):
        self.closed = True


class FakeProducer:
    def __init__(self, **config):
        self.sent = []

    def send(self, topic, key, value):
        self.sent.append((topic, key, value))


def test_connect_retries_through_refusals_and_outages(monkeypatch):
    failures = [ValueError("Invalid file object: None"), NoBrokersAvailable()]

    def consumer(*topics, **config):
        if failures:
            raise failures.pop(0)
        return FakeConsumer(*topics, **config)

    monkeypatch.setattr(bus_module, "KafkaConsumer", consumer)
    monkeypatch.setattr(bus_module, "KafkaProducer", FakeProducer)
    bus = KafkaBus(KAFKA)
    assert bus.connect(threading.Event(), retry_every=0)
    assert bus.consumer.topics == ("data", "cmd")
    assert "group_id" not in bus.consumer.config  # Every tracker instance must see every message


def test_connect_gives_up_when_stopped(monkeypatch):
    monkeypatch.setattr(bus_module, "KafkaConsumer", lambda *a, **k: (_ for _ in ()).throw(NoBrokersAvailable()))
    stop = threading.Event()
    stop.set()
    assert not KafkaBus(KAFKA).connect(stop)


def test_poll_reads_every_partition_in_time_order(monkeypatch):
    monkeypatch.setattr(bus_module, "KafkaConsumer", FakeConsumer)
    monkeypatch.setattr(bus_module, "KafkaProducer", FakeProducer)
    bus = KafkaBus(KAFKA)
    bus.connect(threading.Event())
    # v1 only read partition 0 and only its last message
    bus.consumer.batches = {"data-0": [Record("data", b"a", b"1", 10), Record("data", b"a", b"2", 30)],
                            "data-1": [Record("data", b"b", b"3", 20)],
                            "cmd-0": [Record("cmd", b"status", b"", 25)]}
    assert bus.poll() == [("data", b"a", b"1"), ("data", b"b", b"3"), ("cmd", b"status", b""), ("data", b"a", b"2")]
    bus.send(b"event", b"{}")
    assert bus.producer.sent == [("out", b"event", b"{}")]
