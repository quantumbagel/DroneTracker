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
        self.unblocked = threading.Event()
        self.unblocked.set()

    def send(self, topic, key, value):
        self.unblocked.wait()  # The real send() blocks for up to a minute while it has no metadata for the topic
        self.sent.append((topic, key, value))

    def flush(self, timeout):
        pass

    def close(self, timeout):
        pass


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
    bus.consumer.batches = {"data-0": [Record("data", b"a", b"1", 10_000), Record("data", b"a", b"2", 30_000)],
                            "data-1": [Record("data", b"b", b"3", 20_000)],
                            "cmd-0": [Record("cmd", b"status", b"", 25_000)],
                            "cmd-1": [Record("cmd", b"status", b"", -1)]}  # -1: the record has no timestamp
    assert bus.poll() == [("cmd", b"status", b"", None), ("data", b"a", b"1", 10.0), ("data", b"b", b"3", 20.0),
                          ("cmd", b"status", b"", 25.0), ("data", b"a", b"2", 30.0)]
    bus.send(b"event", b"{}")
    bus.close()
    assert bus.producer.sent == [("out", b"event", b"{}")]


def test_send_never_blocks_the_caller(monkeypatch):
    monkeypatch.setattr(bus_module, "KafkaConsumer", FakeConsumer)
    monkeypatch.setattr(bus_module, "KafkaProducer", FakeProducer)
    bus = KafkaBus(KAFKA)
    bus.connect(threading.Event())
    bus.producer.unblocked.clear()  # Broker unreachable
    for i in range(bus_module.SEND_QUEUE + 10):  # Overflow is dropped, not waited for
        bus.send(b"event", str(i).encode())
    assert bus.producer.sent == []
    bus.producer.unblocked.set()
    bus.close()
    assert bus.producer.sent[0] == ("out", b"event", b"0")
    assert len(bus.producer.sent) >= bus_module.SEND_QUEUE
