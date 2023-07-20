from sensecam_control import vapix_control, vapix_config
import ruamel.yaml
import keyboard

config_yaml = ruamel.yaml.YAML()
config = config_yaml.load(open('config.yml'))
print("Establishing connection to camera... ", end='')
camera = vapix_control.CameraControl(config['login']['ip'], config['login']['username'], config['login']['password'])
image_control = vapix_config.CameraConfiguration(config['login']['ip'], config['login']['username'],
                                                 config['login']['password'])
print('done')
is_recording = False
while True:
    up_down = int(keyboard.is_pressed('w')) - int(keyboard.is_pressed('s'))
    left_right = int(keyboard.is_pressed('d')) - int(keyboard.is_pressed('a'))
    zoom = int(keyboard.is_pressed('up'))-int(keyboard.is_pressed('down'))
    if keyboard.is_pressed('e'):
        print("Taking a picture...")
        rc = image_control.get_jpeg_request()
        if rc == 'image saved':
            print("Succesful!")
    if keyboard.is_pressed('v'):
        if not is_recording:
            print("Starting to record")

    camera.continuous_move(pan=left_right * 100, tilt=up_down * 100, zoom=zoom*100)
