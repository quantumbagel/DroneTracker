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

            if not os.path.exists(self.recording_storage_location):
                os.makedirs(self.recording_storage_location)
            recordings = sorted([file for file in os.listdir(self.recording_storage_location)
                                 if file.endswith(".mkv")])

            for message in messages:
                if message.key == b"track_camera" and message.value in VALID_STATUS:
                    # Track_camera command with valid mode
                    log.info(f"Successfully received new status from Kafka server status={message.value}")
                    self.status = message.value
                    updated = True
                    self.producer.send(self.output_topic, key=b"track_camera", value=b"success")
                    continue

                elif message.key == b"track_camera" and message.value not in VALID_STATUS:
                    # Track_camera command with invalid mode
                    log.error(f"Received invalid track_camera mode: {message.value}")
                    self.producer.send(self.output_topic, key=b"track_camera", value=b"failure")
                    continue

                elif message.key == b"list_recordings":  # Handle list_recording feature
                    log.info("Received request for list of recordings, responding...")
                    self.producer.send(self.output_topic, key=b"list_recordings",
                                       value='\n'.join(recordings).encode("utf-8"))
                    self.producer.flush()  # Force send
                    continue

                elif message.key == b"download_recording":  # Handle download_recording feature
                    log.info("Received request for download of recording {}, transferring file in separate thread...")
                    try:
                        # Format: download_recording <recording number> <oeo_ip>
                        recording_num = int(message.value.split()[0])
                        oeo_server_ip = message.value.split()[1]
                    except IndexError or ValueError:
                        log.error(f"Invalid arguments from verb download_recording (input was '{message.value}'")
                        continue

                    def send_recording(identification):
                        """
                        Nested function to run the netcat command in a thread
                        :param identification: the ID of the recording worker
                        """
                        netcat = os.system(f"netcat -N {oeo_server_ip} {self.oeo_port} < {recordings[recording_num]}")
                        if netcat:
                            log.error("Failed to download recording, returning failure")
                            self.producer.send(self.output_topic, key=b"download_recording",
                                               value=f"failure {recording_num}".encode("utf-8"))
                        else:
                            log.info("Successfully transferred recording, returning success")
                            self.producer.send(self.output_topic, key=b"download_recording",
                                               value=f"success {recording_num}".encode("utf-8"))
                        self.export_threads.pop(identification)

                    # Add a new recording worker to the poll
                    self.export_threads.update({len(self.export_threads):
                                                threading.Thread(target=send_recording,
                                                                 args=[len(self.export_threads)])})
                    self.export_threads[len(self.export_threads) - 1].start()  # Start the worker
                    continue

                log.error(f"Received invalid message from Kafka server! message={message.key} / {message.value}."
                          f" Ignoring message")  # Invalid key from the server
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
