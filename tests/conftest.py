import copy
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import mav  # noqa: E402,F401  (sets MAVLINK20 before pymavlink is imported)


class FakeLog:
    """Stands in for mav.log.RunLog; records everything."""

    def __init__(self):
        self.records = []

    def event(self, kind, msg="", level=None, **fields):
        self.records.append(("event", kind, msg, fields))

    def warning(self, kind, msg="", **fields):
        self.records.append(("warning", kind, msg, fields))

    def error(self, kind, msg="", **fields):
        self.records.append(("error", kind, msg, fields))

    def command(self, name, status, **fields):
        self.records.append(("command", name, status, fields))

    def telemetry(self, snapshot):
        self.records.append(("telemetry", snapshot))

    def kinds(self):
        return [r[1] for r in self.records]


@pytest.fixture
def fake_log():
    return FakeLog()


@pytest.fixture(scope="session")
def base_raw():
    with open(REPO_ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def raw(base_raw):
    return copy.deepcopy(base_raw)


@pytest.fixture
def mission_raw(raw):
    """config.yaml with every TBD filled with a plausible value."""
    fill = {
        "start_switch": {"rc_channel": 7, "pwm_threshold": 1700},
        "positions": {"box_lat": -35.3632, "box_lon": 149.1652, "box_ground_alt_rel_home_m": -9.0},
        "altitudes": {"cruise_alt_rel_home_m": 8.0, "balcony_approach_alt_rel_home_m": 3.0,
                      "balcony_handoff_height_m": 0.5},
        "speeds": {"cruise_speed_m_s": 3.0, "descent_speed_m_s": 0.5, "final_descent_speed_m_s": 0.3,
                   "max_centering_speed_m_s": 0.5, "centering_tolerance_m": 0.15},
        "geometry": {"camera_offset_m": [-0.2, 0, 0.05], "lidar_offset_m": [-0.2, 0.03, 0.05],
                     "lidar_mount_height_m": 0.2, "box_thickness_m": 0.15, "magnet_clearance_m": 0.05},
        "camera": {"frame_rate": 30},
        "rangefinder": {"baro_lidar_warn_m": 1.0},
        "pickup": {"contact_stall_s": 1.0, "contact_stall_vz_m_s": 0.1, "magnet_settle_s": 2.0},
        "timeouts": {"search_timeout_s": 120, "reacquire_timeout_s": 5, "approach_timeout_s": 60,
                     "descent_timeout_s": 20, "balcony_tag_timeout_s": 30, "mission_timeout_s": 600},
        "battery_gps": {"min_start_v": 24.0, "return_v": 21.6, "min_sats": 10},
    }
    for section, values in fill.items():
        raw[section].update(values)
    return raw
