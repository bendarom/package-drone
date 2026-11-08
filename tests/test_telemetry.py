import pytest
from pymavlink import mavutil

from mav.telemetry import Telemetry

mavlink = mavutil.mavlink
enc = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def distance(cm, orientation=25):
    return enc.distance_sensor_encode(0, 10, 1200, cm, 0, 0, orientation, 0)


@pytest.fixture
def tel():
    clock = Clock()
    t = Telemetry(0.1, 6.0, clock=clock)
    t.clock = clock
    return t


def test_none_before_messages(tel):
    assert tel.mode is None and tel.rangefinder_m is None and tel.battery_v is None
    assert tel.rangefinder_valid is False
    assert tel.age("ATTITUDE") is None


def test_rangefinder_validity(tel):
    tel.update(distance(150))
    assert tel.rangefinder_m == 1.5 and tel.rangefinder_valid
    tel.update(distance(5))          # blind zone (sensor min 10 cm)
    assert not tel.rangefinder_valid
    tel.update(distance(800))        # above config max_reliable 6 m
    assert not tel.rangefinder_valid


def test_non_downward_rangefinder_ignored(tel):
    tel.update(distance(150))
    tel.update(distance(30, orientation=0))
    assert tel.rangefinder_m == 1.5


def test_heartbeat_mode_and_armed(tel):
    tel.update(enc.heartbeat_encode(2, 3, mavlink.MAV_MODE_FLAG_SAFETY_ARMED | 1, 4, 4))
    assert tel.mode == "GUIDED" and tel.armed is True


def test_position_units(tel):
    tel.update(enc.global_position_int_encode(0, -353632620, 1491652370, 600000, 8500, 0, 0, -120, 9000))
    assert tel.lat == pytest.approx(-35.363262)
    assert tel.rel_alt_m == 8.5
    assert tel.climb_rate_m_s == 1.2
    assert tel.heading_deg == 90.0


def test_rate_measurement(tel):
    for i in range(60):            # 10 Hz for 6 s
        tel.clock.t = i * 0.1
        tel.update(enc.attitude_encode(0, 0, 0, 0, 0, 0, 0))
    assert tel.rate_hz("ATTITUDE") == pytest.approx(10, abs=0.5)
    tel.clock.t += 10              # stream stopped
    assert tel.rate_hz("ATTITUDE") == 0.0


def test_rc_channel(tel):
    ch = [1500] * 18
    ch[6] = 1900
    tel.update(enc.rc_channels_encode(0, 18, *ch, 255))
    assert tel.rc_channel(7) == 1900
    assert tel.rc_channel(19) is None


def test_ekf_ok(tel):
    good = (mavlink.EKF_ATTITUDE | mavlink.EKF_VELOCITY_HORIZ | mavlink.EKF_VELOCITY_VERT
            | mavlink.EKF_POS_HORIZ_ABS | mavlink.EKF_POS_VERT_ABS | mavlink.EKF_POS_HORIZ_REL)
    tel.update(enc.ekf_status_report_encode(good, 0, 0, 0, 0, 0))
    assert tel.ekf_ok
    tel.update(enc.ekf_status_report_encode(good | mavlink.EKF_CONST_POS_MODE, 0, 0, 0, 0, 0))
    assert not tel.ekf_ok
