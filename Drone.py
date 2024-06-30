import logging
import time
from datetime import datetime

from kafka.errors import NoBrokersAvailable
import kafka
import json



class Drone:
    """
    A class to represent the drone and handle the connection and location of it
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
        self.get_drone_position()
        self.most_recent = 0

    def connect(self):
        try:
            self.consumer = kafka.KafkaConsumer(bootstrap_servers=[self.connection])
        except NoBrokersAvailable:
            self.consumer = None
            return False
        self.consumer.subscribe([self.topic])

    def update_drone_position(self):
        """
        Get the position of the drone and save it to the class
        :return: nothing
        """

        msg = self.consumer.poll()
        if len(msg):
            self.log.debug("Successfully received message from Kafka server")
            msg = msg[kafka.TopicPartition(self.topic, 0)][-1]
        else:
            self.log.debug("No new data!")
            return
        t = (datetime.utcfromtimestamp(msg.timestamp // 1000)
             .replace(microsecond=msg.timestamp % 1000 * 1000).timestamp())
        self.most_recent = t  # This is a new most recent
        value = json.loads(msg.value)
        try:
            self.lat = value["position"]["latitude"]
            self.long = value["position"]["longitude"]
            self.alt = value["position"]["altitude"]
            self.vx = value["velocity"]["x"]
            self.vy = value["velocity"]["y"]
            self.vz = value["velocity"]["z"]
        except KeyError:
            self.log.error(f"Position data not present!\nData: {value}")

    def get_drone_position(self):
        """
        Update and return the drone's location
        :return: latitude, longitude, altitude
        """
        exit_code = self.update_drone_position()
        if exit_code:
            return -1
        return self.lat, self.long, self.alt, self.vx, self.vy, self.vz
