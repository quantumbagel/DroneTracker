# DroneTracker
*trigonometry, kafka, and drone tracking walk into a bar*
**Disclaimer: This guide is written for Linux users. This program should work great on all operating systems, just adapt as necessary.**

### What does this do?
This program controls AXIS cameras supporting VAPIX to track objects (drones) and record video of the drones.

Its features include
* Customizable recording triggers
* Can zoom to fit drone in view or with a certain amount of space around it
* Can handle drone software crashes or disconnects and quickly recover
* Can support as many drones as you need via config
* Works with any AXIS PTZ camera supporting VAPIX or any ArduPilot/MavLink based drone
and many more!

### Configuration Options

| Configuration Option                                          | Description                                                                                                                                                 |
|---------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| camera/alt                                                    | The altitude (from sea level) for the camera's lens.                                                                                                        |
| camera/lat, camera/long                                       | The latitude and longitude of the camera's lens.                                                                                                            |
| camera/radius_activate                                        | The maximum radius that the drone can be for the camera to be active                                                                                        |
| camera/offset                                                 | The camera's offset from north (clockwise)                                                                                                                  |
| camera/deactivate_pos/pan, camera/deactivate_pos/tilt         | The pan/tilt to deactivate the camera to when it is not in use.                                                                                             |
| camera/min_step                                               | The minimum change in the pan/tilt (degrees) from the camera's current position for the program to send an update                                           |
| camera/min_zoom_step                                          | The minimum change in the zoom cycles from the camera's current zoom for the program to send an update                                                      |
| camera/delay                                                  | The delay after the program detects it should not be recording for the camera to stop recording.                                                            |
| camera/maximum_zoom                                           | The maximum zoom of the camera.                                                                                                                             |
| camera/lead                                                   | The amount of seconds to lead the drone based on its velocity.                                                                                              |
| camera/zoom_error                                             | How much space to have outside of the zoom (1.2 has 20% more space, 0.8 has 80% of the space)                                                               |
| drone/x, drone/y, drone/z                                     | The size of the drone (height, width, depth)                                                                                                                |
| scale/dist, scale/width                                       | At 1x zoom, looking straight ahead, the camera's horizontal FOV at `dist` meters away is `width`. This has been calibrated for the AXIS Q-8615E PTZ camera. |
| camera_login/ip, camera_login/username, camera_login/password | The ip, username, and password of the camera.                                                                                                               |
| kafka/ip                                                      | The ip of the Kafka server to connect to for both command and data updates                                                                                  |
| kafka/data_topic, kafka/command_topic                         | The topics the program should receive data and command information from, respectively                                                                       |
| kafka/hz                                                      | The amount of times per second to check for updates on both data and command streams                                                                        |
| experiment/stop_recording_after                               | The amount of time after the last packet is received from Kafka before the recording should be stopped and the camera deactivated                           |
| debug                                                         | The log level of the program. Valid options: "debug" "info" "warning" "error"                                                                               |


##### Running in a Dockerfile

Make sure Docker is installed. 

Change `config.yml`'s options to what you want.

Then, enter the project directory and run this oneliner: `sudo docker compose build && sudo docker compose up -d`
You should be good to go!
