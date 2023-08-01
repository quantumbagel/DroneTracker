# CameraDistance
A drone-following script for NC State's AERPAW drones

**Disclaimer: This guide is written for Linux users. This program should work great on all operating systems, just adapt as necessary.**

### What does this do?
This program controls AXIS cameras supporting VAPIX to track MavLink/ArduPilot drones and record video of them.

### Configuration Options

|Configuration Option|Description|
|-|-|
|camera/alt|The altitude (from sea level) for the camera's lens.|
|camera/lat, camera/long| The latitude and longitude of the camera's lens.|
|camera/radius_activate)|The maximum radius that the drone can be for the camera to be active|
|camera/offset| The camera's offset from north (clockwise)|
|camera/deactivate_pos/pan, camera/deactivate_pos/tilt|The pan/tilt to deactivate the camera to when it is not in use.|
|camera/min_step|The minimum change in the pan/tilt (degrees) from the camera's current position for the program to send an update|
|camera/min_zoom_step|The minimum change in the zoom cycles from the camera's current zoom for the program to send an update|
|camera/wait|The delay between ticks. 0 should be fine, but if you are running on an old CPU, 0.1 will lower usage drastically|
|camera/activate_method|How to detect if the camera should be recording. armed: when the drone arms/disarms, file: when the file 'record' starts with a 1 or 0, start/stop recording, relative-height: you must put "relative-height5" or a number.|
|camera/delay|The delay after the program detects it should not be recording for the camera to stop recording.|
|camera/maximum_zoom|The maximum zoom of the camera.|
|camera/is_upside_down|Is the camera upside down?|
|camera/zoom_error|How much space to have outside of the zoom (1.2 has 20% more space, 0.8 has 80% of the space)|
|drone/address| The drone addresses. Format: name: [prefix, start port, number of ports to check sequentially]|
|drone/x, drone/y, drone/z|The size of the drone (height, width, depth)|
|drone/msg_timeout| The timeout of the camera's messages to connect to the drone|
|scale/dist, scale/width| At 1x zoom, looking straight ahead, the camera's horizontal FOV at `dist` meters away is `width`. This has been calibrated for the AXIS Q-8615E PTZ camera.|
|login/ip, login/username, login/password|The ip, username, and password of the camera.|
|debug| The log level of the program. 0 is none, 1 is normal, 2 is debug.|

### Installation Guide

You can either run this locally or inside a Docker container.

##### Running Locally

Enter the directory, and run `pip3 install -r requirements.txt`

Change `config.yaml`'s options to what you want.

Then, just run `python3 dronetracker.py` and you should be good!


##### Running in a Dockerfile

Make sure Docker is installed. 

Change `config.yaml`'s options to what you want.

Then, enter the project directory and run this one liner: `sudo docker compose build && sudo docker compose up -d`
You should be good to go!



### If Things Don't Go Right

Just open an issue! I am active and will try my best to help with fixing your issue!
