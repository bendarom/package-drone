import serial
import time

ser = serial.Serial('/dev/serial0', 115200, timeout=1)

print("Listening for raw ArduPilot MAVLink packets...")
try:
    while True:
        if ser.in_waiting > 0:
            # Read whatever bytes are available in the buffer
            raw_data = ser.read(ser.in_waiting)
            # Print the data as a hex string to confirm reception
            print(f"Received {len(raw_data)} bytes: {raw_data.hex()}")
        time.sleep(0.1)
except KeyboardInterrupt:
    print("Stopped.")
finally:
    ser.close()
