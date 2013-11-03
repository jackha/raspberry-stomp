# test rotary encoder and displays
import socket
import rotary_encoder
import threading
import datetime
import wiringpi2
from Adafruit_LEDBackpack.Adafruit_7Segment import SevenSegment
from Adafruit_LEDBackpack.Adafruit_8x8 import EightByEight

from server import server
from time import sleep
from subprocess import Popen
import settings

import os

# react on ctrl-c
import signal 
import sys
def signal_handler(signal, frame):
        sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)


ENC1_PIN_A = 0  # use wiring pin numbers here
ENC1_PIN_B = 7
#ENC1_PIN_C = 6  # Push button

ENC2_PIN_A = 12  # use wiring pin numbers here
ENC2_PIN_B = 3
#ENC2_PIN_C = 3  # Push button

PUSH_BUTTON_PINS = [2, 13, 15, 16, 1, 4]

EIGHT_BY_EIGHT_ADDRESS = 0x70
EIGHT_BY_EIGHT_BRIGHTNESS = 0

SEVEN_SEGMENT_ADDRESS= 0x74
SEVEN_SEGMENT_BRIGHTNESS = 0

SLEEP_TIME = 0.02  # In seconds: give audio more time.
SLEEP_TIME_ROTARY = 0.005


# These should be files in pd directory (without .pd extension). Keys are displayed names
# The effects must all have 2 audio inlets and 8 normal inlets, 2 audio outlets and 1 normal outlet
AVAILABLE_EFFECTS = [
    {'display_name': '....', 'patch_name': '0', 'settings': []},
    {'display_name': ' dly', 'patch_name': '1', 'settings': settings.spectraldelay},
    {'display_name': 'vibr', 'patch_name': '2', 'settings': settings.stepvibrato},
    {'display_name': 'syth', 'patch_name': '3', 'settings': settings.synth},
    {'display_name': 'hexi', 'patch_name': '4', 'settings': settings.hexxiter},
    # {'display_name': 'ring', 'patch_name': '5'},
    # {'display_name': 'revb', 'patch_name': '6'},
    # {'display_name': 'bold', 'patch_name': '7'},
    # {'display_name': 'psyn', 'patch_name': '8'},
    # {'display_name': 'wird', 'patch_name': '9'},
    # {'display_name': 'robo', 'patch_name': '10'},
    # {'display_name': 'bsyn', 'patch_name': '11'},
]


class Effects(object):

    # Option names in Pd.
    option_names = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']

    def __init__(self, loader_socket, available_effects):
        self.current_effect = 0  # by index of AVAILABLE_EFFECTS
        self.loader_socket = loader_socket
        self.loaded = False
        self.available_effects = available_effects
        self.current_settings = 8*[0]
        self.step_sizes = 8*[1]  # for settings
        #self.load()

    @property
    def settings(self):
        return self.available_effects[self.current_effect]['settings']

    @property
    def patch_name(self):
        display_name = AVAILABLE_EFFECTS[self.current_effect]['patch_name']
        return display_name

    @property
    def display_name(self):
        return AVAILABLE_EFFECTS[self.current_effect]['display_name']

    def up(self):
        self.unload()
        self.current_effect = (self.current_effect + 1) % len(self.available_effects)
        self.load()
        self.set_default_settings()

    def down(self):
        self.unload()
        self.current_effect = (self.current_effect - 1) % len(self.available_effects)
        self.load()
        self.set_default_settings()

    def load(self):
        if self.loaded:
            return
        self.loaded = True
        self.loader_socket.sendall('load %s;' % self.patch_name)
        sleep(0.1)  # essential! Or Pd will sometimes stop with a segmentation fault.
        self.send_sock = init_pd_socket()

    def set_default_settings(self):
        """ Set all default settings and determine step sizes"""
        for idx, setting in enumerate(self.settings):
            self.current_settings[idx] = setting['default']
            if setting['type'] == 'float':
                self.step_sizes[idx] = (setting['max'] - setting['min']) / 100.
            else:
                self.step_sizes[idx] = 1
            self.setting(idx, 0)

    def setting(self, idx, delta):
        """ Add delta to setting and update to Pd. 

        Return curr value"""
        if idx >= len(self.settings):
            return
        self.current_settings[idx] += delta * self.step_sizes[idx]
        if self.current_settings[idx] < self.settings[idx]['min']:
            self.current_settings[idx] = self.settings[idx]['min']
        if self.current_settings[idx] > self.settings[idx]['max']:
            self.current_settings[idx] = self.settings[idx]['max']
        if self.settings[idx]['type'] == 'float':
            self.send_sock.sendall('%s %f;' % (self.option_names[idx], self.current_settings[idx]))
        else:
            self.send_sock.sendall('%s %d;' % (self.option_names[idx], self.current_settings[idx]))
        return self.current_settings[idx]

    def unload(self):
        if not self.loaded:
            return
        self.send_sock.close()
        sleep(.1)  # essential!
        self.loaded = False
        self.loader_socket.sendall('unload %s;' % self.patch_name)

    def settings_as_eight(self, selected=None):
        """Return byte array of 8 settings. Optionally give index for selected setting"""
        lookup_add = [128, 1, 2, 4, 8, 16, 32, 64]
        result = []
        for row in range(0, len(self.settings)):
            row_value = lookup_add[0] if selected==row else 0
            normalized_value = (7*(float(self.current_settings[row]) - self.settings[row]['min']) / 
                    (self.settings[row]['max'] - self.settings[row]['min']))
            for col in range(0, 7):
                if normalized_value >= col:
                    row_value += lookup_add[col+1]

            result.append(row_value)
        for row in range(len(self.settings), 8):
            result.append(0)
        return result


class EightByEightPlus(EightByEight):
    """Better Eight By Eight by being smarter"""
    def __init__(self, brightness=15, *args, **kwargs):
        result = super(EightByEightPlus, self).__init__(*args, **kwargs)
        self.disp.setBrightness(brightness)
        return result

    def set_values(self, values, selected=0):
        lookup_add = [1, 2, 4, 8, 16, 32, 64]
        #print 'display values'
        for row in range(0, 8):
            # strangely 128 is the first pixel, not 1
            row_value = 128 if row == selected else 0
            for col in range(0, 7):
                if values[row] > col * 10:
                    row_value += lookup_add[col]
            #print 'row, rowvalue %d %d' % (row, row_value)
            grid.writeRowRaw(row, row_value, update=False)
        grid.disp.writeDisplay()

    def grid_array(self, arr):
        """Grid array"""
        lookup_add = [128, 1, 2, 4, 8, 16, 32, 64]
        
        for y in range(8):
            byte_value = 0
            for x in range(8):
                byte_value += lookup_add[x] * arr[y][x]
                #grid.setPixel(x, y, arr[y][x])
            grid.writeRowRaw(y, byte_value, update=False)
        grid.disp.writeDisplay()

    def bytes_array(self, arr):
        """Grid array"""
        for y in range(8):
            grid.writeRowRaw(y, arr[y], update=False)
        grid.disp.writeDisplay()

class SevenSegmentPlus(SevenSegment):
    letters = {
        ' ': 0,
        'a': 1 + 2 + 4 + 16 + 32 + 64,
        'b': 4 + 8 + 16 + 32 + 64,
        'c': 8 + 16 + 64,
        'd': 2 + 4 + 8 + 16 + 64,
        'e': 1 + 2 + 8 + 16 + 32 + 64,
        'f': 1 + 16 + 32 + 64,
        'g': 1 + 2 + 4 + 8 + 32 + 64,
        'h': 4 + 16 + 32 + 64,
        'i': 4,
        'j': 2 + 4 + 8 + 16,
        'k': 2 + 4 + 16 + 32 + 64,
        'l': 2 + 4,
        'm': 1 + 2 + 4 + 16 + 32,
        'n': 4 + 16 + 64,
        'o': 4 + 8 + 16 + 64,
        'p': 1 + 2 + 16 + 32 + 64,
        'q': 1 + 2 + 4 + 32 + 64,
        'r': 16 + 64,
        's': 1 + 4 + 8 + 32 + 64,
        't': 8 + 16 + 32 + 64,
        'u': 4 + 8 + 16,
        'v': 2 + 4 + 8 + 16 + 32,
        'w': 2 + 4 + 8 + 16 + 32,
        'x': 2 + 4 + 16 + 32 + 64,
        'y': 2 + 4 + 8 + 32 + 64,
        'z': 1 + 2 + 8 + 16 + 64,
        '0': 1 + 2 + 4 + 8 + 16 + 32,
        '1': 2 + 4,
        '2': 1 + 2 + 8 + 16 + 64,
        '3': 1 + 2 +4 + 8 + 64,
        '4': 2 + 4 + 32 + 64,
        '5': 1 + 4 + 8 + 32 + 64,
        '6': 4 + 8 + 16 + 32 + 64,
        '7': 1 + 2 + 4,
        '8': 1 + 2 + 4 + 8 + 16 + 32 + 64,
        '9': 1 + 2 + 4 + 8 + 32 + 64,
        '-': 64,
        '.': 128,
    }

    def __init__(self, brightness=15, *args, **kwargs):
        result = super(SevenSegmentPlus, self).__init__(*args, **kwargs)
        self.disp.setBrightness(brightness)
        return result

    def write(self, text):
        """Write text on display, must have 4 characters!"""
        text = text.lower()
        self.writeDigitRaw(0, self.letters[text[0]])
        self.writeDigitRaw(1, self.letters[text[1]])
        self.writeDigitRaw(3, self.letters[text[2]])
        self.writeDigitRaw(4, self.letters[text[3]])


"""For Janita: make smiley on display"""
smiley = [
    [0,0,0,0,0,0,0,0],
    [0,0,1,0,0,1,0,0],
    [0,0,1,0,0,1,0,0],
    [0,0,1,0,0,1,0,0],
    [1,0,0,0,0,0,0,1],
    [0,1,0,0,0,0,1,0],
    [0,0,1,1,1,1,0,0],
    [0,0,0,0,0,0,0,0],
]

janita = [
    [1,0,1,0,1,0,0,0],
    [1,1,1,0,1,0,0,0],
    [1,0,1,0,1,0,0,0],
    [0,0,0,0,0,0,0,0],
    [0,0,1,0,0,1,0,0],
    [0,0,1,0,1,0,1,0],
    [1,0,1,0,1,1,1,0],
    [0,1,0,0,1,0,1,0]]

janita2 = [
    [1,0,0,1,0,1,0,0],
    [1,1,0,1,0,1,0,0],
    [1,0,1,1,0,1,0,0],
    [1,0,0,1,0,1,0,0],
    [0,0,0,0,0,0,1,0],
    [0,1,1,1,0,1,0,1],
    [0,0,1,0,0,1,1,1],
    [0,0,1,0,0,1,0,1]]

smiley_cry = [
    [0,0,0,0,0,0,0,0],
    [0,0,1,0,0,1,0,0],
    [0,0,1,0,0,1,0,0],
    [0,0,1,0,0,1,0,0],
    [0,0,0,0,0,0,0,0],
    [0,0,1,1,1,1,0,0],
    [0,1,0,0,0,0,1,0],
    [0,1,0,0,0,0,1,0],
]


# Communication with Pd
class Communication():
    def __init__(self, *args, **kwargs):
        self.changes = False
        self.message = None

    def set(self, message):
        print 'echo %s from pd server' % message
        self.message = message
        self.changes = True
        #self.sock.sendall(message)  # echo all messages

    def get(self):
        message = self.message
        changes = self.changes
        self.changes = False
        self.message = None
        return changes, message


class ListenThread(threading.Thread):
    """Listen to incoming events from Pd patch"""
    def __init__(self, communication, *args, **kwargs):
        self.communication = communication
        super(ListenThread, self).__init__(*args, **kwargs)

    def run(self):
        print "Start listening to Pd..."
        server('localhost', 3001, communication=self.communication)
        print "Stopped listening to Pd."


class PushButtons(object):
    def __init__(self, button_pins, sleep_time=0.05):
        self.gpio = wiringpi2.GPIO(wiringpi2.GPIO.WPI_MODE_PINS)
        self.button_pins = button_pins

        for button_pin in self.button_pins:
            self.gpio.pinMode(button_pin, self.gpio.INPUT)
            self.gpio.pullUpDnControl(button_pin, self.gpio.PUD_UP)

    def get_button(self, index):
        return self.gpio.digitalRead(self.button_pins[index]) == wiringpi2.GPIO.LOW


class Pd(object):
    """ Start a given patch.
    """
    def __init__(self):
        self.pd_proc = Popen("pd-extended -jack -nogui pd/loader.pd", 
            shell=True, preexec_fn=os.setsid)

    def shutdown(self):
        print 'stopping Pd %r...' % self.pd_proc.pid
        os.killpg(self.pd_proc.pid, signal.SIGTERM)


def init_pd_socket():
    # Create a socket (SOCK_STREAM means a TCP socket)
    # client of puredata: use 'netreceive 3000' in pd
    print "init send socket to Pd..."
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    send_sock.connect(('localhost', 3000))
    return send_sock
    

if __name__ == '__main__':
    print "Raspberry-Stomp"

    #pd = Pd()
    #sleep(2)  # TODO: improve
    #print "Starting Pd-extended..."
    #pd = Pd()
    #pd.start();
    #pd_proc = Popen("pd-extended -jack -nogui pd/server.pd", shell=True, preexec_fn=os.setsid)
    #sleep(2)

    grid = EightByEightPlus(
        address=EIGHT_BY_EIGHT_ADDRESS, 
        brightness=EIGHT_BY_EIGHT_BRIGHTNESS)
    segment = SevenSegmentPlus(
        address=SEVEN_SEGMENT_ADDRESS, 
        brightness=SEVEN_SEGMENT_BRIGHTNESS)

    values = 8*[0]
    selected = 0
    selected_idx = 0

    #encoder = rotary_encoder.RotaryEncoder(A_PIN, B_PIN)
    encoder1 = rotary_encoder.RotaryEncoder.Worker(
       ENC1_PIN_A, ENC1_PIN_B, sleep_time=SLEEP_TIME_ROTARY)
    encoder1.start()

    encoder2 = rotary_encoder.RotaryEncoder.Worker(
       ENC2_PIN_A, ENC2_PIN_B, sleep_time=SLEEP_TIME_ROTARY)
    encoder2.start()

    push_buttons = PushButtons(PUSH_BUTTON_PINS)

    # We use this socket to switch patches
    loader_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    loader_socket.connect(('localhost', 5000))
    effects = Effects(loader_socket, AVAILABLE_EFFECTS)
    effects.load()

    #sleep(0.1)  # essential! Or Pd will sometimes stop with a segmentation fault.
    #send_sock = init_pd_socket()

    print "listen to Pd..."
    # Listen to Pd
    communication = Communication()
    server_thread = ListenThread(communication=communication)  # listen to messages from Pd
    server_thread.daemon = True
    server_thread.start()



    #initialized = False
    disp_needs_updating = True
    now = datetime.datetime.now()
    disp_timer_expiration = now
    quit_timer_expiration = now
    startup = False
    push = {}
    pushed_in = {}  # You want to trigger a push only once.
    for i in range(len(PUSH_BUTTON_PINS)):
        pushed_in[i] = False

    running = True


    while(running):
        # read rotary encoder
        # delta1 = 0
        # delta2 = 0
        delta1 = encoder1.get_delta()
        delta2 = encoder2.get_delta()
        now = datetime.datetime.now()

        #some_push = False
        for i in range(len(PUSH_BUTTON_PINS)):
            push[i] = push_buttons.get_button(i)
            #if push[i]:
            #    some_push = True

        comm_changes, comm_msg = communication.get()

        if comm_changes:
            print "TODO: Do something with %r" % comm_msg

        if push[0]:
            disp_timer_expiration = now + datetime.timedelta(seconds=2)
            grid.grid_array(janita)

            disp_needs_updating = True

        if push[1]:
            disp_timer_expiration = now + datetime.timedelta(seconds=2)
            grid.grid_array(janita2)

            disp_needs_updating = True

        if push[3] and not pushed_in[3]:
            effects.up()
            selected_idx = 0
            pushed_in[2] = True
            disp_needs_updating = True

        if push[5] and not pushed_in[5]:
            #running = False;
            pushed_in[5] = True
            quit_timer_expiration = now + datetime.timedelta(seconds=2)
            #send_sock.sendall('b_e bla;')

        if push[5] and pushed_in[5] and now <= quit_timer_expiration:
            seconds_left = (quit_timer_expiration - now).seconds + 1 # It's always < 60 sec
            segment.write('t % 2d' % (-seconds_left))

        if push[5] and pushed_in[5] and now > quit_timer_expiration:
            running = False

        if not push[5] and pushed_in[5]:
            # Just released button
            disp_needs_updating = True

        for i in range(len(PUSH_BUTTON_PINS)):
            if not push[i]:
                pushed_in[i] = False


        if delta1 != 0 or delta2 != 0:
            selected = (selected + delta2) % (8*8)  # make it slower
            selected_idx = selected/8

            value = effects.setting(selected_idx, delta1)

            # Set 7 segment
            # Set hours
            segment.writeDigit(0, int(value/1000)%10)
            segment.writeDigit(1, int(value/100)%10) 
            # Set minutes
            segment.writeDigit(3, int(value / 10) % 10)   # Tens
            segment.writeDigit(4, int(value) % 10)        # Ones
            # Toggle color
            #segment.setColon(0)              # Toggle colon at 1Hz

            grid.bytes_array(effects.settings_as_eight(selected=selected_idx))

            disp_timer_expiration = datetime.datetime.now() + datetime.timedelta(seconds=2)
            disp_needs_updating = True

        if startup:
            startup = False

        # grid display: default view
        if datetime.datetime.now() > disp_timer_expiration and disp_needs_updating:
            segment.write(effects.display_name)
            grid.grid_array(smiley)
            disp_needs_updating = False
            push_timer_expiration = datetime.datetime.now()

        sleep(SLEEP_TIME)

    #send_sock.sendall('volume 0;')
    effects.unload()
    grid.grid_array(smiley_cry)
    segment.write(' bye')

