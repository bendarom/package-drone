"""Driver for the Benewake TFmini Plus LiDAR rangefinder over UART.

Wiring (TFmini Plus -> Pi 5 GPIO header):
    Red   (5V)  -> Pin 2  (5V)
    Black (GND) -> Pin 6  (GND)
    White (RX)  -> Pin 8  (GPIO14 / TXD)
    Green (TX)  -> Pin 10 (GPIO15 / RXD)

Before running, enable the PL011 UART on those pins and free it from the
login shell:
    sudo raspi-config  ->  Interface Options -> Serial Port
        "login shell over serial?"      -> No
        "serial port hardware enabled?" -> Yes
    sudo reboot

This exposes the sensor at /dev/ttyAMA0 (confirm with `ls /dev/ttyAMA*`).
"""

import sys
import time

import serial

FRAME_HEADER = 0x59
DEFAULT_PORT = "/dev/ttyAMA0"
DEFAULT_BAUDRATE = 115200
MIN_SIGNAL_STRENGTH = 100  # below this the reading is unreliable per datasheet


class TFMiniPlus:
    def __init__(self, port=DEFAULT_PORT, baudrate=DEFAULT_BAUDRATE, timeout=1.0):
        self.serial = serial.Serial(port, baudrate=baudrate, timeout=timeout)

    def close(self):
        self.serial.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def read_distance(self):
        """Block for one frame and return (distance_cm, strength) or None if invalid/timed out."""
        if self.serial.read(1) != bytes([FRAME_HEADER]):
            return None
        if self.serial.read(1) != bytes([FRAME_HEADER]):
            return None

        payload = self.serial.read(7)
        if len(payload) != 7:
            return None  # read timed out mid-frame

        checksum = (FRAME_HEADER + FRAME_HEADER + sum(payload[:6])) & 0xFF
        if checksum != payload[6]:
            return None

        distance_cm = payload[0] | (payload[1] << 8)
        strength = payload[2] | (payload[3] << 8)

        if strength < MIN_SIGNAL_STRENGTH:
            return None  # too weak / out of range to trust

        return distance_cm, strength


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PORT
    with TFMiniPlus(port=port) as lidar:
        print(f"Reading TFmini Plus on {port}...")
        while True:
            reading = lidar.read_distance()
            if reading is None:
                continue
            distance_cm, strength = reading
            print(f"distance: {distance_cm / 100:.2f} m  (strength {strength})")


if __name__ == "__main__":
    main()
