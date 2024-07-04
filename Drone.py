import logging
import time
from datetime import datetime
from kafka.errors import NoBrokersAvailable
import kafka
import json


class Drone:
    """
    A class to represent the drone and get its data via a Kafka topic.
    """

    def __init__(self, connection="localhost:9092", topic="dronetracker-data", timeout=1):
        """
        Initialize and connect to the drone.
        :param connection: where to connect to the Kafka server
        """
        self.start_time = time.time()
        self.lat = self.long = self.alt = self.vx = self.vy = self.vz = None
        self.timeout = timeout
        self.consumer = None
        self.connection = connection
        self.topic = topic
        self.connect()
        self.log = logging.getLogger('Drone')
        self.most_recent = 0

    def connect(self):
        """
        Restart and connect to the Kafka server.
        """
        try:
            self.consumer = kafka.KafkaConsumer(bootstrap_servers=[self.connection])
        except NoBrokersAvailable:
            self.consumer = None
            return False
        self.consumer.subscribe([self.topic])

    def update(self):
        """
        Get the position of the drone and save it to the class
        :return: nothing
        """
        log = self.log.getChild("update")
        msg = self.consumer.poll()
        if len(msg):  # is there new data?
            log.debug("Successfully received message from Kafka server")
            msg = msg[kafka.TopicPartition(self.topic, 0)][-1]  # We need to get the most recent message, thus the -1
        else:
            log.debug("No new data!")  # We don't need to do anything, just return.
            if time.time() - self.most_recent > self.timeout:  # We can go into "deactivate" mode
                self.most_recent = 0
            # The most recent data is already saved
            return

        self.most_recent = msg.timestamp // 1000  # This is a new most recent
        value = json.loads(msg.value)  # Load the JSON data in
        try:
            # Get data from dictionary and save it to class instance variables
            self.lat = value["position"]["latitude"]
            self.long = value["position"]["longitude"]
            self.alt = value["position"]["altitude"]
            self.vx = value["velocity"]["x"]
            self.vy = value["velocity"]["y"]
            self.vz = value["velocity"]["z"]
        except KeyError:
            # We got a KeyError - the data isn't valid!
            self.log.error(f"Position data not present!\nData: {value}")

    def reset(self):
        """
        Reset the drone's data so it isn't used in future experiments
        """
        self.lat = self.long = self.alt = self.vx = self.vy = self.vz = None

