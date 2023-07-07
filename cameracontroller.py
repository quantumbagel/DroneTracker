from sensecam_control import vapix_control, vapix_config
import ruamel.yaml
import keyboard
config = ruamel.yaml.YAML()
config = config.load('config.yml')
print("Establishing connection to camera... ", end='')
camera = vapix_control.CameraControl(config['login']['ip'], config['login']['username'], config['login']['password'])
image_control = vapix_config.CameraConfiguration(config['login']['ip'], config['login']['username'], config['login']['password'])
print('done')


while True:
    up_down = int(keyboard.is_pressed('w')) - int(keyboard.is_pressed('s'))
    left_right = int(keyboard.is_pressed('d')) - int(keyboard.is_pressed('a'))
    print(up_down, left_right)
    if keyboard.is_pressed('e'):
        print("Taking a picture...")
        image_control.get_jpeg_request()
    camera.continuous_move(pan=up_down*100, tilt=left_right*100)
