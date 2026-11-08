"""SITL ONLY: change the flight mode from a second connection, acting as a pilot
or GCS would, to test the mode watcher. Never run against the real FC.

  python sitl/mode_poke.py LOITER
"""

import argparse
import os
import sys

os.environ.setdefault("MAVLINK20", "1")
from pymavlink import mavutil  # noqa: E402

DEFAULT_CONNECTION = "tcp:127.0.0.1:5763"   # SITL SERIAL2; mission code uses 5762


def poke(mode, connection=DEFAULT_CONNECTION, timeout_s=5):
    """Send DO_SET_MODE as a GCS (sysid 255). Returns True if the FC accepted it."""
    if not connection.startswith("tcp:127.0.0.1:"):
        raise SystemExit("mode_poke is SITL only (expects tcp:127.0.0.1:<port>)")
    m = mavutil.mavlink_connection(connection, source_system=255,
                                   source_component=mavutil.mavlink.MAV_COMP_ID_MISSIONPLANNER)
    try:
        if m.wait_heartbeat(timeout=timeout_s) is None:
            print(f"no heartbeat on {connection}", file=sys.stderr)
            return False
        modes = {name: num for num, name in mavutil.mode_mapping_acm.items()}
        m.mav.command_long_send(m.target_system, m.target_component,
                                mavutil.mavlink.MAV_CMD_DO_SET_MODE, 0,
                                mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, modes[mode],
                                0, 0, 0, 0, 0)
        ack = m.recv_match(type="COMMAND_ACK", blocking=True, timeout=timeout_s,
                           condition=f"COMMAND_ACK.command=={mavutil.mavlink.MAV_CMD_DO_SET_MODE}")
        ok = ack is not None and ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED
        print(f"mode_poke {mode}: {'accepted' if ok else ack}")
        return ok
    finally:
        m.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("mode")
    p.add_argument("--connection", default=DEFAULT_CONNECTION)
    a = p.parse_args()
    sys.exit(0 if poke(a.mode, a.connection) else 1)
