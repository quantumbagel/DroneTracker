import math
import os
import threading
import time
import logging
import kafka
from kafka import KafkaConsumer, KafkaProducer

VALID_STATUS = [b"off", b"on", b"auto"]


class KafkaGateway:
    """
    A class to watch for changes to the dronetracker-command Kafka topic
    """

    def __init__(self, connection: str, command_topic: str = "dronetracker_command",
                 output_topic: str = "dronetracker_output", recording_storage_location: str = "recordings",
                 oeo_port: int = 15321):
        """
        Initialize the Gateway class
        :param connection: Kafka connection IP
        :param command_topic: Kafka topic to watch for
        :return: None
        """
        self.connection = connection  # Connection IP
        self.consumer = KafkaConsumer(bootstrap_servers=[connection])
        self.producer = KafkaProducer(bootstrap_servers=[connection])
        self.command_topic = command_topic
        self.output_topic = output_topic
        self.recording_storage_location = recording_storage_location
        self.consumer.subscribe([self.command_topic])
        self.log = logging.getLogger('Gateway')
        self.oeo_port = oeo_port
        self.export_threads = {}
        self.status = "off"  # We default to "off" on startup.
        # Should the command  topic send confirmation that experiment is active?

    def update(self):
        """
        Update the status from the Kafka server
        :return: whether new data was received
        """
        log = self.log.getChild("update")
        msg = self.consumer.poll()  # Update consumer data
        updated = False
        if len(msg):  # is there new data?
            messages = msg[kafka.TopicPartition(self.command_topic, 0)]
            # Get deterministic list of recordings without subprocess
            recordings = sorted([file for file in os.listdir(self.recording_storage_location)
                                 if file.endswith(".mkv")])
            for message in messages:
                if message.value in VALID_STATUS:  # Ensure validity
                    log.info(f"Successfully received new status from Kafka server status={message.value}")
                    self.status = message.value
                    updated = True
                    continue
                elif message.value == b"list_recordings":
                    log.info("Received request for list of recordings, responding...")
                    self.producer.send(self.output_topic, value='\n'.join(recordings).encode("utf-8"))
                elif message.value.startswith(b"download_recording"):
                    log.info("Received request for download of recording {}, transferring file in separate thread...")
                    try:
                        recording_num = int(message.value.split()[1])
                        oeo_server_ip = message.value.split()[2]
                    except IndexError or ValueError:
                        log.error(f"Invalid arguments from verb download_recording (input was '{message.value}'")
                        continue

                    def send_recording(identification):
                        os.system(f"netcat -N {oeo_server_ip} {self.oeo_port} < {recordings[recording_num]}")
                        self.export_threads.pop(identification)

                    self.export_threads.update({len(self.export_threads):
                                                    threading.Thread(target=send_recording,
                                                                     args=[len(self.export_threads)])})
                    self.export_threads[len(self.export_threads) - 1].start()

                log.error(f"Received invalid message from Kafka server! status={message.value}. Ignoring message")
        else:
            log.debug("No new data received from poll action.")  # We don't need to do anything, just return.
            # The most recent data is already saved
            return False
        return updated

    def wait_for_status(self, status: str, hz: int = 10):
        """
        Wait for the server to send a certain status type.
        :param status: the desired status type
        :param hz: the number of times per second to poll (0 = as fast as possible)
        :return: None
        """
        if hz == 0:
            hz = math.inf  # Prevent ZeroDivisionError
        start = time.time()
        log = self.log.getChild("wait_for_status")  # Get logging set up
        status = status.encode("utf-8")  # Convert to bytes
        if status not in VALID_STATUS:  # Ensure validity
            raise ValueError(f"Received invalid status from call to wait_for_status()! status={status}")
        while True:
            # Use a timer for the action
            cycle_start = time.time()
            updated = self.update()  # Get new information from Kafka
            if updated and self.status == status:  # We are done!
                break
            cycle_end = time.time()
            delta = 1 / hz - (cycle_end - cycle_start)  # Calculate sleep time
            if delta > 0:  # We can only sleep if we need to
                log.debug(f"Now sleeping for {round(delta, 2)} seconds")
                time.sleep(delta)
        end = time.time()
        log.info(f"Received message of status {status} from Kafka server after {round(end - start, 2)} seconds")
