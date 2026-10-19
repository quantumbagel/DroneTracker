FROM python:3.12-slim
WORKDIR /opt/DroneTracker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY dronetracker.py config.yml ./
COPY tracker ./tracker
COPY utils ./utils
CMD ["python", "dronetracker.py"]
