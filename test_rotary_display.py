# test rotary encoder and displays
import socket
import rotary_encoder
import threading
from Adafruit_LEDBackpack.Adafruit_7Segment import SevenSegment
from Adafruit_LEDBackpack.Adafruit_8x8 import EightByEight

from server import server

# react on ctrl-c
import signal 
import sys
def signal_handler(signal, frame):
        sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)



ENC1_PIN_A = 5  # use wiring pin numbers here
ENC1_PIN_B = 4
ENC1_PIN_C = 6  # Push button

ENC2_PIN_A = 0  # use wiring pin numbers here
ENC2_PIN_B = 2
ENC2_PIN_C = 3  # Push button


class EightByEightPlus(EightByEight):
    """Better Eight By Eight by being smarter"""
    def __init__(self, *args, **kwargs):
        result = super(EightByEightPlus, self).__init__(*args, **kwargs)

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


class SevenSegmentPlus(SevenSegment):
    pass


"""For Janita: make smiley on display"""
smiley = [
    [0,0,1,1,1,1,0,0],
    [0,1,0,0,0,0,1,0],
    [1,0,1,0,0,1,0,1],
    [1,0,1,0,0,1,0,1],
    [1,1,0,0,0,0,1,1],
    [1,0,1,1,1,1,0,1],
    [0,1,0,0,0,0,1,0],
    [0,0,1,1,1,1,0,0]]

smiley_neutral = [
    [0,0,1,1,1,1,0,0],
    [0,1,0,0,0,0,1,0],
    [1,0,1,0,0,1,0,1],
    [1,0,1,0,0,1,0,1],
    [1,0,0,0,0,0,0,1],
    [1,0,1,1,1,1,0,1],
    [0,1,0,0,0,0,1,0],
    [0,0,1,1,1,1,0,0]]


# Communication with Pd
class Communication():
    def __init__(self, sock, *args, **kwargs):
        self.sock = sock

    def set(self, message):
        print 'echo %s' % message
        sock.sendall(message)  # echo all messages


class ListenThread(threading.Thread):
    """Listen to incoming events from Pd"""
    def __init__(self, communication, *args, **kwargs):
        self.communication = communication
        super(ListenThread, self).__init__(*args, **kwargs)

    def run(self):
        print "Start listening to Pd..."
        server('localhost', 3001, communication=self.communication)
        print "Stopped listening to Pd."


if __name__ == '__main__':
    print "Starting Raspberry-Stomp..."

    grid = EightByEightPlus(address=0x70)
    segment = SevenSegmentPlus(address=0x74)

    values = 8*[0]
    selected = 0
    startup = True

    #encoder = rotary_encoder.RotaryEncoder(A_PIN, B_PIN)
    encoder1 = rotary_encoder.RotaryEncoder.Worker(ENC1_PIN_A, ENC1_PIN_B)
    encoder1.start()

    encoder2 = rotary_encoder.RotaryEncoder.Worker(ENC2_PIN_A, ENC2_PIN_B)
    encoder2.start()

    # Create a socket (SOCK_STREAM means a TCP socket)
    # client of puredata: use 'netreceive 3000' in pd
    print "init send socket to Pd..."
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    send_sock.connect(('localhost', 3000))

    print "listen to Pd..."
    # Listen to Pd
    communication = Communication(sock=send_sock)
    server_thread = ListenThread(communication=communication)  # listen to messages from Pd
    server_thread.daemon = True
    server_thread.start()

    print "init to Pd..."
    send_sock.sendall('init;')  # makes Pd connect back on port 3001

    while(True):
        # read rotary encoder
        delta1 = encoder1.get_delta()
        delta2 = encoder2.get_delta()

        if delta1 != 0 or delta2 != 0 or startup:
            selected += delta2 % (8*8)  # make it slower
            values[selected/8] += delta1
            value = values[selected]
            print 'change value: selected %s value %s delta1 %d delta2 %d' % (
                selected, value, delta1, delta2) 
            
            # Set 7 segment
            # Set hours
            segment.writeDigit(0, int(value/1000)%10)
            segment.writeDigit(1, int(value/100)%10) 
            # Set minutes
            segment.writeDigit(3, int(value / 10) % 10)   # Tens
            segment.writeDigit(4, value % 10)        # Ones
            # Toggle color
            #segment.setColon(0)              # Toggle colon at 1Hz

            # send test message to Pd server
            print "Volume to Pd..."
            send_sock.sendall('volume %f;' % (value*0.001))

            # if value < 20:
            #     grid.grid_array(smiley_neutral)
            # elif value < 60:
            #     grid.grid_array(smiley)
            # else:
            grid.set_values(values, selected=selected)

            startup = False
        # sleep(0.001)
