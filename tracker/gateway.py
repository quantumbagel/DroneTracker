"""
Handles commands from the Kafka command topic. Each command is a message whose key names the command:

    track_camera        on | off | auto           -> track_camera: success | failure
    select              <drone_id> | none          -> select: success | failure
    priority            <id>,<id>,...              -> priority: success
    status                                         -> status: <JSON>
    list_recordings                                -> list_recordings: newline-separated file names
    download_recording  <index|name> <host> [port] -> download_recording: success|failure <index|name>
                        streams the file over TCP to host:port (default recording/download_port)
"""
import ipaddress
import json
import logging
import os
import re
import socket
import threading

from tracker.config import MODES

log = logging.getLogger("gateway")

_HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")
RECORDING_SUFFIXES = (".mkv", ".jsonl")


def valid_host(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(_HOSTNAME.match(host))


class Gateway:
    def __init__(self, app, cfg, send):
        """
        :param app: the App, for set_mode / select / set_priority / status
        :param send: function(key: bytes, value: bytes) publishing to the output topic
        """
        self.app = app
        self.send = send
        self.directory = cfg["recording"]["dir"]
        self.download_port = cfg["recording"]["download_port"]
        self.handlers = {"track_camera": self._track_camera, "select": self._select, "priority": self._priority,
                         "status": self._status, "list_recordings": self._list_recordings,
                         "download_recording": self._download_recording}

    def reply(self, key, value):
        self.send(key.encode("utf-8"), value.encode("utf-8"))

    def handle(self, key, value):
        name = key.decode("utf-8", errors="replace") if key else ""
        text = value.decode("utf-8", errors="replace").strip() if value else ""
        handler = self.handlers.get(name)
        if handler is None:
            log.warning(f"Ignoring unknown command {name!r} (value {text!r})")
            self.reply("error", f"unknown command {name!r}")
            return
        log.info(f"Command {name} {text!r}")
        try:
            handler(text)
        except Exception as error:  # A malformed command must never abort the tracking loop
            log.exception(f"Command {name} {text!r} failed")
            self.reply("error", f"{name} failed: {error}")

    def _track_camera(self, text):
        mode = text.lower()
        if mode not in MODES:
            log.error(f"Invalid track_camera mode {text!r}")
            self.reply("track_camera", "failure")
            return
        self.app.set_mode(mode)
        self.reply("track_camera", "success")

    def _select(self, text):
        if text.lower() in ("", "none", "auto"):
            self.app.select(None)
        elif not self.app.select(text):
            self.reply("select", "failure")
            return
        self.reply("select", "success")

    def _priority(self, text):
        self.app.set_priority([p.strip() for p in text.split(",") if p.strip()])
        self.reply("priority", "success")

    def _status(self, _):
        self.reply("status", json.dumps(self.app.status()))

    def recordings(self):
        if not os.path.isdir(self.directory):
            return []
        return sorted(f for f in os.listdir(self.directory) if f.endswith(RECORDING_SUFFIXES))

    def _list_recordings(self, _):
        self.reply("list_recordings", "\n".join(self.recordings()))

    def _download_recording(self, text):
        parts = text.split()
        token = parts[0] if parts else ""
        files = self.recordings()
        name, host, port = None, None, self.download_port
        if len(parts) in (2, 3):
            if token.isascii() and token.isdigit() and int(token) < len(files):
                name = files[int(token)]
            elif token in files:
                name = token
            host = parts[1] if valid_host(parts[1]) else None
            if len(parts) == 3:
                port = int(parts[2]) if parts[2].isascii() and parts[2].isdigit() and 0 < int(parts[2]) < 65536 \
                    else None
        if name is None or host is None or port is None:
            log.error(f"Invalid download_recording request {text!r}")
            self.reply("download_recording", f"failure {token}")
            return
        threading.Thread(target=self._send_file, args=(os.path.join(self.directory, name), host, port, token),
                         name=f"download-{name}", daemon=True).start()

    def _send_file(self, path, host, port, token):
        try:
            with socket.create_connection((host, port), timeout=10) as connection, open(path, "rb") as file:
                connection.sendfile(file)
                connection.shutdown(socket.SHUT_WR)  # Like `netcat -N`: tell the receiver we're done
        except OSError as error:
            log.error(f"Sending {path} to {host}:{port} failed: {error}")
            self.reply("download_recording", f"failure {token}")
            return
        log.info(f"Sent {path} to {host}:{port}")
        self.reply("download_recording", f"success {token}")
