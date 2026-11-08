"""Send gate: what the connection may and may not send."""

import pytest
from pymavlink import mavutil

from mav.connection import COPTER_MODES, gate_reason

mavlink = mavutil.mavlink
enc = mavlink.MAVLink(None, srcSystem=1, srcComponent=191)


def cmd(command, *params):
    p = list(params) + [0] * (7 - len(params))
    return enc.command_long_encode(1, 1, command, 0, *p)


HEARTBEAT = enc.heartbeat_encode(mavlink.MAV_TYPE_ONBOARD_CONTROLLER, mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 4)
STATUSTEXT = enc.statustext_encode(6, b"hello")
PARAM_READ = enc.param_request_read_encode(1, 1, b"GUID_TIMEOUT", -1)
INTERVAL = cmd(mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 30, 50000)
SET_GUIDED = cmd(mavlink.MAV_CMD_DO_SET_MODE, 1, COPTER_MODES["GUIDED"])
VELOCITY = enc.set_position_target_local_ned_encode(0, 1, 1, 8, 0b0000111111000111, 0, 0, 0, 0.5, 0, 0, 0, 0, 0, 0, 0)
ARM = cmd(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)

ALWAYS = [HEARTBEAT, STATUSTEXT, PARAM_READ, INTERVAL]
CONTROL = [SET_GUIDED, VELOCITY, ARM]
NEVER = [
    enc.param_set_encode(1, 1, b"GUID_TIMEOUT", 5.0, mavlink.MAV_PARAM_TYPE_REAL32),
    cmd(mavlink.MAV_CMD_DO_SET_PARAMETER, 1, 5),
    cmd(mavlink.MAV_CMD_PREFLIGHT_STORAGE, 1),
    cmd(mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH),
    cmd(mavlink.MAV_CMD_DO_SET_MODE, 1, COPTER_MODES["RTL"]),
    cmd(mavlink.MAV_CMD_DO_SET_MODE, 1, COPTER_MODES["SMART_RTL"]),
    enc.set_mode_encode(1, 1, COPTER_MODES["RTL"]),
]


@pytest.mark.parametrize("run_mode", ["real", "sitl", "shadow"])
@pytest.mark.parametrize("tripped", [False, True])
@pytest.mark.parametrize("msg", ALWAYS, ids=lambda m: m.get_type())
def test_always_allowed(msg, run_mode, tripped):
    assert gate_reason(msg, run_mode, tripped) is None


@pytest.mark.parametrize("run_mode", ["real", "sitl", "shadow"])
@pytest.mark.parametrize("tripped", [False, True])
@pytest.mark.parametrize("msg", NEVER, ids=lambda m: m.get_type())
def test_never_allowed(msg, run_mode, tripped):
    assert gate_reason(msg, run_mode, tripped).startswith("never:")


@pytest.mark.parametrize("msg", CONTROL, ids=lambda m: m.get_type())
def test_control_allowed_when_in_charge(msg):
    assert gate_reason(msg, "real", False) is None
    assert gate_reason(msg, "sitl", False) is None


@pytest.mark.parametrize("msg", CONTROL, ids=lambda m: m.get_type())
def test_control_blocked_in_shadow(msg):
    assert gate_reason(msg, "shadow", False).startswith("shadow mode")


@pytest.mark.parametrize("msg", CONTROL, ids=lambda m: m.get_type())
def test_control_blocked_after_trip(msg):
    assert gate_reason(msg, "real", True).startswith("mode watcher tripped")
