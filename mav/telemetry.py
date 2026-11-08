"""Latest telemetry from the vehicle.

The connection's reader thread calls update() with every message from the
autopilot. Accessors return None until the message has arrived; check age() for
staleness. rate_hz() is measured over the last RATE_WINDOW_S seconds, so preflight
can check that a stream is arriving at the requested rate.
"""

import collections
import threading
import time

from pymavlink import mavutil

RATE_WINDOW_S = 5.0
MAV_DISTANCE_SENSOR_DOWN = 25   # MAV_SENSOR_ROTATION_PITCH_270

EKF_REQUIRED_FLAGS = (
    mavutil.mavlink.EKF_ATTITUDE
    | mavutil.mavlink.EKF_VELOCITY_HORIZ
    | mavutil.mavlink.EKF_VELOCITY_VERT
    | mavutil.mavlink.EKF_POS_HORIZ_ABS
    | mavutil.mavlink.EKF_POS_VERT_ABS
)
EKF_BAD_FLAGS = mavutil.mavlink.EKF_CONST_POS_MODE | mavutil.mavlink.EKF_UNINITIALIZED


def copter_mode_name(custom_mode):
    return mavutil.mode_mapping_acm.get(custom_mode, f"MODE_{custom_mode}")


class Telemetry:
    def __init__(self, rangefinder_min_m, rangefinder_max_m, clock=time.monotonic):
        self.rangefinder_min_m = rangefinder_min_m
        self.rangefinder_max_m = rangefinder_max_m
        self._clock = clock
        self._lock = threading.Lock()
        self._latest = {}    # type -> (msg, t)
        self._arrivals = collections.defaultdict(collections.deque)

    def update(self, msg, now=None):
        mtype = msg.get_type()
        if mtype == "DISTANCE_SENSOR" and msg.orientation != MAV_DISTANCE_SENSOR_DOWN:
            return
        now = self._clock() if now is None else now
        with self._lock:
            self._latest[mtype] = (msg, now)
            q = self._arrivals[mtype]
            q.append(now)
            while q and q[0] < now - RATE_WINDOW_S:
                q.popleft()

    def get(self, mtype):
        with self._lock:
            entry = self._latest.get(mtype)
        return entry[0] if entry else None

    def age(self, mtype):
        """Seconds since the last message of this type, or None if never received."""
        with self._lock:
            entry = self._latest.get(mtype)
        return None if entry is None else self._clock() - entry[1]

    def rate_hz(self, mtype):
        now = self._clock()
        with self._lock:
            q = self._arrivals.get(mtype)
            if not q:
                return 0.0
            recent = [t for t in q if t >= now - RATE_WINDOW_S]
        if not recent:
            return 0.0
        if now - recent[0] >= RATE_WINDOW_S * 0.9:
            # Count over the whole window, so a stream that stops decays to 0.
            return len(recent) / RATE_WINDOW_S
        if len(recent) < 2:
            return 0.0
        # Stream younger than the window (just connected): mean inter-arrival rate.
        return (len(recent) - 1) / max(recent[-1] - recent[0], 1e-6)

    # --- HEARTBEAT ---
    @property
    def mode(self):
        hb = self.get("HEARTBEAT")
        return None if hb is None else copter_mode_name(hb.custom_mode)

    @property
    def armed(self):
        hb = self.get("HEARTBEAT")
        return None if hb is None else bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)

    # --- position ---
    @property
    def lat(self):
        m = self.get("GLOBAL_POSITION_INT")
        return None if m is None else m.lat / 1e7

    @property
    def lon(self):
        m = self.get("GLOBAL_POSITION_INT")
        return None if m is None else m.lon / 1e7

    @property
    def rel_alt_m(self):
        """Altitude above home (baro/EKF), meters."""
        m = self.get("GLOBAL_POSITION_INT")
        return None if m is None else m.relative_alt / 1000.0

    @property
    def climb_rate_m_s(self):
        """Vertical speed, up positive (GLOBAL_POSITION_INT.vz is down positive)."""
        m = self.get("GLOBAL_POSITION_INT")
        return None if m is None else -m.vz / 100.0

    @property
    def heading_deg(self):
        m = self.get("GLOBAL_POSITION_INT")
        return None if m is None or m.hdg == 65535 else m.hdg / 100.0

    # --- attitude ---
    @property
    def attitude(self):
        """(roll, pitch, yaw) in radians."""
        m = self.get("ATTITUDE")
        return None if m is None else (m.roll, m.pitch, m.yaw)

    # --- rangefinder ---
    @property
    def rangefinder_m(self):
        """Raw downward reading in meters (lens to surface)."""
        m = self.get("DISTANCE_SENSOR")
        return None if m is None else m.current_distance / 100.0

    @property
    def rangefinder_valid(self):
        """Reading within both the sensor's own limits and config's valid range."""
        m = self.get("DISTANCE_SENSOR")
        if m is None:
            return False
        d = m.current_distance / 100.0
        return (m.min_distance / 100.0 <= d <= m.max_distance / 100.0
                and self.rangefinder_min_m <= d <= self.rangefinder_max_m)

    # --- state ---
    @property
    def landed_state(self):
        m = self.get("EXTENDED_SYS_STATE")
        return None if m is None else m.landed_state

    @property
    def on_ground(self):
        s = self.landed_state
        return None if s is None else s == mavutil.mavlink.MAV_LANDED_STATE_ON_GROUND

    @property
    def throttle_pct(self):
        m = self.get("VFR_HUD")
        return None if m is None else m.throttle

    def rc_channel(self, n):
        """PWM of RC channel n (1-18), or None."""
        m = self.get("RC_CHANNELS")
        if m is None or not 1 <= n <= 18:
            return None
        v = getattr(m, f"chan{n}_raw")
        return None if v == 65535 else v

    @property
    def battery_v(self):
        m = self.get("SYS_STATUS")
        if m is not None and m.voltage_battery != 65535:
            return m.voltage_battery / 1000.0
        b = self.get("BATTERY_STATUS")
        if b is not None:
            cells = [v for v in b.voltages if v != 65535]
            return sum(cells) / 1000.0 if cells else None
        return None

    @property
    def gps_fix_type(self):
        m = self.get("GPS_RAW_INT")
        return None if m is None else m.fix_type

    @property
    def gps_sats(self):
        m = self.get("GPS_RAW_INT")
        return None if m is None else m.satellites_visible

    @property
    def ekf_ok(self):
        m = self.get("EKF_STATUS_REPORT")
        if m is None:
            return None
        return (m.flags & EKF_REQUIRED_FLAGS) == EKF_REQUIRED_FLAGS and not (m.flags & EKF_BAD_FLAGS)

    def snapshot(self, rate_types=()):
        """Key values for logging and readouts; rates for the given message types."""
        att = self.attitude
        snap = {
            "mode": self.mode,
            "armed": self.armed,
            "lat": self.lat,
            "lon": self.lon,
            "rel_alt_m": self.rel_alt_m,
            "climb_m_s": self.climb_rate_m_s,
            "heading_deg": self.heading_deg,
            "roll_deg": None if att is None else round(_deg(att[0]), 2),
            "pitch_deg": None if att is None else round(_deg(att[1]), 2),
            "rangefinder_m": self.rangefinder_m,
            "rangefinder_valid": self.rangefinder_valid,
            "landed_state": self.landed_state,
            "throttle_pct": self.throttle_pct,
            "battery_v": self.battery_v,
            "gps_fix": self.gps_fix_type,
            "gps_sats": self.gps_sats,
            "ekf_ok": self.ekf_ok,
        }
        if rate_types:
            snap["rates_hz"] = {t: round(self.rate_hz(t), 1) for t in rate_types}
        return snap


def _deg(rad):
    return rad * 57.29577951308232
