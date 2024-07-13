FROM ubuntu:23.10
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get -y install git pkg-config python3 python3-dev python3-pip
WORKDIR /opt/DroneTracker
COPY . /opt/DroneTracker
RUN /usr/bin/python3 -m pip install --break-system-packages -r requirements.txt
CMD /usr/bin/python3 dronetracker.py