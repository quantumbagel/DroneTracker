"""
A simple program to control the camera using arrow keys and the keyboard.
"""
from sensecam_control import vapix_control, vapix_config
import ruamel.yaml
import keyboard
config_yaml = ruamel.yaml.YAML()
config = config_yaml.load(open('../config.yml'))
print("Establishing connection to camera... ", end='')
camera = vapix_control.CameraControl(config['camera_login']['ip'], config['camera_login']['username'], config['camera_login']['password'])
image_control = vapix_config.CameraConfiguration(config['camera_login']['ip'], config['camera_login']['username'],
                                                 config['camera_login']['password'])

print('done')
is_recording = False
max_cooldown = 20
cooldown = 0
while True:
    up_down = int(keyboard.is_pressed('w')) - int(keyboard.is_pressed('s'))
    left_right = int(keyboard.is_pressed('d')) - int(keyboard.is_pressed('a'))
    zoom = int(keyboard.is_pressed('up'))-int(keyboard.is_pressed('down'))
    if keyboard.is_pressed('e'):
        print("Taking a picture...")
        rc = image_control.get_jpeg_request()
        if rc == 'image saved':
            print("Succesful!")
    if keyboard.is_pressed('q'):
        print("WIPERING")

    if not cooldown:
        if keyboard.is_pressed('v'):
            if not is_recording:
                print("Starting to record")

                iden = image_control.start_recording('SD_DISK')[0]
                print(iden)
                is_recording = True
            else:
                if image_control.stop_recording(iden):
                    print(":)")
                else:
                    print(":(")
                is_recording = False
            cooldown = max_cooldown
    if cooldown:
        cooldown -= 1
    camera.continuous_move(pan=left_right * 100, tilt=up_down * 100, zoom=zoom*100)