"""MAVLink connection, telemetry, parameter check and mode watcher.

MAVLINK20 must be set before pymavlink is first imported so mavutil uses MAVLink 2.
"""

import os

os.environ.setdefault("MAVLINK20", "1")
