"""MAVLink link to the FC (real serial/UDP or SITL TCP).

One reader thread receives everything and feeds Telemetry, the ModeWatcher, and
anyone waiting for a COMMAND_ACK or PARAM_VALUE. One housekeeping thread sends our
1 Hz HEARTBEAT, writes telemetry snapshots and watches for link loss.

Every outgoing message goes through the send gate (gate_reason):
- always allowed: HEARTBEAT, STATUSTEXT, parameter reads, SET_MESSAGE_INTERVAL
- never allowed: parameter writes, RTL (CLAUDE.md hard rules)
- everything else is "control": blocked in shadow mode and once the mode watcher
  has seen a mode change this code didn't make.
Every send except routine heartbeats is logged, including blocked ones.
"""

import threading
import time

from pymavlink import mavutil

from .mode_watcher import ModeWatcher
from .telemetry import Telemetry, copter_mode_name

mavlink = mavutil.mavlink

MAV_COMP_ID_AUTOPILOT1 = mavlink.MAV_COMP_ID_AUTOPILOT1
COPTER_MODES = {name: num for num, name in mavutil.mode_mapping_acm.items()}
# "This code never commands RTL" covers every return-to-launch flavour.
RTL_MODES = {COPTER_MODES[m] for m in ("RTL", "SMART_RTL", "AUTO_RTL")}

ALWAYS_TYPES = {"HEARTBEAT", "STATUSTEXT", "PARAM_REQUEST_READ", "PARAM_REQUEST_LIST"}
ALWAYS_COMMANDS = {mavlink.MAV_CMD_SET_MESSAGE_INTERVAL}
NEVER_TYPES = {"PARAM_SET", "PARAM_EXT_SET"}
NEVER_COMMANDS = {
    mavlink.MAV_CMD_DO_SET_PARAMETER: "parameter writes are not allowed",
    mavlink.MAV_CMD_PREFLIGHT_STORAGE: "parameter writes are not allowed",
    mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH: "this code never commands RTL",
}
STATUSTEXT_MAX = 50
STATUSTEXT_PREFIX = "Pi: "


class LinkError(Exception):
    pass


def gate_reason(msg, run_mode, tripped):
    """None if msg may be sent, otherwise why not."""
    mtype = msg.get_type()
    if mtype in NEVER_TYPES:
        return "never: parameter writes are not allowed"
    if mtype in ("COMMAND_LONG", "COMMAND_INT"):
        if msg.command in NEVER_COMMANDS:
            return f"never: {NEVER_COMMANDS[msg.command]}"
        if msg.command == mavlink.MAV_CMD_DO_SET_MODE and int(msg.param2) in RTL_MODES:
            return "never: this code never commands RTL"
        if msg.command in ALWAYS_COMMANDS:
            return None
    if mtype == "SET_MODE" and msg.custom_mode in RTL_MODES:
        return "never: this code never commands RTL"
    if mtype in ALWAYS_TYPES:
        return None
    if run_mode == "shadow":
        return "shadow mode: only heartbeat, statustext, parameter reads and message intervals"
    if tripped:
        return "mode watcher tripped: no commands after a mode change this code didn't make"
    return None


def _describe(msg):
    """Fields worth logging for a sent message."""
    d = msg.to_dict()
    d.pop("mavpackettype", None)
    return d


class MavLink:
    def __init__(self, cfg, log):
        self.cfg = cfg
        self.log = log
        c = cfg.connection
        self.run_mode = c.run_mode
        self.sysid = c.sysid
        self.telemetry = Telemetry(cfg.rangefinder.min_valid_m, cfg.rangefinder.max_reliable_m)
        self.watcher = ModeWatcher(log, shadow=self.run_mode == "shadow")
        self.watcher.add_callback(self._on_foreign_mode)
        self.master = None
        self._send_lock = threading.Lock()
        self._wait_lock = threading.Lock()
        self._ack_waiters = {}      # command id -> list of [event, msg]
        self._param_waiters = {}    # param name -> list of [event, msg]
        self._stop = threading.Event()
        self._threads = []
        self._last_vehicle_hb = None
        self._link_lost = False
        self.rate_types = tuple(cfg.telemetry.rates_hz.keys())

    # ------------------------------------------------------------------ lifecycle
    def connect(self):
        c = self.cfg.connection
        self.log.event("connecting", c.connection_string, run_mode=self.run_mode,
                       sysid=c.sysid, compid=c.compid)
        # baud is used for serial devices only; autoreconnect only affects tcp.
        self.master = mavutil.mavlink_connection(
            c.connection_string, baud=c.baud, source_system=c.sysid, source_component=c.compid,
            autoreconnect=True)
        self.master.target_system = c.sysid
        self.master.target_component = MAV_COMP_ID_AUTOPILOT1

        self._start_thread(self._housekeeping, "mav-housekeeping")
        hb = self._wait_vehicle_heartbeat(c.connect_timeout_s)
        self.log.event("connected", "vehicle heartbeat received",
                       mode=copter_mode_name(hb.custom_mode),
                       autopilot=hb.autopilot, vehicle_type=hb.type, mavlink_version=hb.mavlink_version)
        self._start_thread(self._reader, "mav-reader")
        return self

    def close(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        if self.master is not None:
            self.master.close()
        self.log.event("disconnected")

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    def _start_thread(self, fn, name):
        t = threading.Thread(target=fn, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def _is_vehicle(self, msg):
        return msg.get_srcSystem() == self.sysid and msg.get_srcComponent() == MAV_COMP_ID_AUTOPILOT1

    def _wait_vehicle_heartbeat(self, timeout_s):
        """First HEARTBEAT from the autopilot itself, ignoring GCS/MAVProxy/other
        companions. Runs before the reader thread starts."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            msg = self.master.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
            if msg is None or not self._is_vehicle(msg) or msg.type == mavlink.MAV_TYPE_GCS:
                continue
            self._on_vehicle_message(msg)
            return msg
        raise LinkError(f"no vehicle HEARTBEAT (sysid {self.sysid}, compid {MAV_COMP_ID_AUTOPILOT1}) "
                        f"within {timeout_s:g} s on {self.cfg.connection.connection_string}")

    # ------------------------------------------------------------------ threads
    def _reader(self):
        while not self._stop.is_set():
            try:
                msg = self.master.recv_match(blocking=True, timeout=0.5)
            except Exception as e:  # serial glitch, socket reset: log and keep going
                self.log.error("recv_error", repr(e))
                time.sleep(0.5)
                continue
            if msg is None or msg.get_type() == "BAD_DATA" or not self._is_vehicle(msg):
                continue
            self._on_vehicle_message(msg)

    def _on_vehicle_message(self, msg):
        mtype = msg.get_type()
        self.telemetry.update(msg)
        if mtype == "HEARTBEAT":
            self._last_vehicle_hb = time.monotonic()
            armed = bool(msg.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            self.watcher.on_heartbeat(copter_mode_name(msg.custom_mode), armed)
        elif mtype == "COMMAND_ACK":
            self._deliver(self._ack_waiters, msg.command, msg)
        elif mtype == "PARAM_VALUE":
            self._deliver(self._param_waiters, msg.param_id, msg)
        elif mtype == "STATUSTEXT":
            self.log.event("fc_statustext", msg.text, severity=msg.severity)

    def _deliver(self, waiters, key, msg):
        with self._wait_lock:
            for w in waiters.get(key, ()):
                w[1] = msg
                w[0].set()

    def _housekeeping(self):
        c = self.cfg.connection
        hb_period = 1.0 / c.heartbeat_hz
        log_period = 1.0 / self.cfg.telemetry.log_hz
        next_hb = next_log = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_hb:
                next_hb = now + hb_period
                self._send_heartbeat()
            if self._last_vehicle_hb is not None:
                silent = now - self._last_vehicle_hb
                if not self._link_lost and silent > c.link_timeout_s:
                    self._link_lost = True
                    self.log.error("link_lost", f"no vehicle HEARTBEAT for {silent:.1f} s")
                elif self._link_lost and silent <= c.link_timeout_s:
                    self._link_lost = False
                    self.log.event("link_restored")
                if now >= next_log:
                    next_log = now + log_period
                    self.log.telemetry(self.telemetry.snapshot(self.rate_types))
            self._stop.wait(0.05)

    def _send_heartbeat(self):
        msg = self.master.mav.heartbeat_encode(
            mavlink.MAV_TYPE_ONBOARD_CONTROLLER, mavlink.MAV_AUTOPILOT_INVALID, 0, 0,
            mavlink.MAV_STATE_ACTIVE)
        try:
            self.send(msg, log=False)
        except Exception as e:
            self.log.error("heartbeat_send_failed", repr(e))

    # ------------------------------------------------------------------ sending
    @property
    def link_ok(self):
        return self._last_vehicle_hb is not None and not self._link_lost

    def gate_reason(self, msg):
        return gate_reason(msg, self.run_mode, self.watcher.tripped)

    def send(self, msg, log=True):
        """Send through the gate. Returns True if sent, False if blocked."""
        reason = self.gate_reason(msg)
        if reason is not None:
            self.log.command(msg.get_type(), f"blocked: {reason}", **_describe(msg))
            return False
        with self._send_lock:
            self.master.mav.send(msg)
        if log:
            self.log.command(msg.get_type(), "sent", **_describe(msg))
        return True

    def _wait_for(self, waiters, key, send_fn, timeout_s):
        """Register a waiter, call send_fn(), wait for the reply. Returns the reply
        message, None on timeout, or False if send_fn reported a block."""
        entry = [threading.Event(), None]
        with self._wait_lock:
            waiters.setdefault(key, []).append(entry)
        try:
            if send_fn() is False:
                return False
            entry[0].wait(timeout_s)
            return entry[1]
        finally:
            with self._wait_lock:
                waiters[key].remove(entry)
                if not waiters[key]:
                    del waiters[key]

    def command_long(self, command, params=(), retries=1, timeout_s=None):
        """COMMAND_LONG and wait for its COMMAND_ACK. Returns the ACK's result
        (MAV_RESULT), None if no ACK, or False if the gate blocked it."""
        timeout_s = self.cfg.connection.command_ack_timeout_s if timeout_s is None else timeout_s
        p = list(params) + [0] * (7 - len(params))
        for attempt in range(retries + 1):
            msg = self.master.mav.command_long_encode(
                self.sysid, MAV_COMP_ID_AUTOPILOT1, command, attempt, *p)
            ack = self._wait_for(self._ack_waiters, command, lambda: self.send(msg), timeout_s)
            if ack is False:
                return False
            if ack is not None:
                self.log.event("command_ack", mavlink.enums["MAV_CMD"][command].name,
                               result=mavlink.enums["MAV_RESULT"][ack.result].name, attempt=attempt)
                return ack.result
        self.log.warning("command_no_ack", mavlink.enums["MAV_CMD"][command].name, attempts=retries + 1)
        return None

    def set_message_intervals(self, rates_hz=None):
        """MAV_CMD_SET_MESSAGE_INTERVAL for each message. Returns {name: accepted}."""
        rates_hz = self.cfg.telemetry.rates_hz if rates_hz is None else rates_hz
        results = {}
        for name, hz in rates_hz.items():
            msg_id = getattr(mavlink, f"MAVLINK_MSG_ID_{name}", None)
            if msg_id is None:
                self.log.error("message_interval", f"unknown MAVLink message {name}")
                results[name] = False
                continue
            result = self.command_long(mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, (msg_id, 1e6 / hz))
            # result is False when blocked; MAV_RESULT_ACCEPTED is 0, so compare by identity.
            ok = result is not False and result == mavlink.MAV_RESULT_ACCEPTED
            results[name] = ok
            if result is None:
                result_name = "no ACK"
            elif result is False:
                result_name = "blocked"
            else:
                result_name = mavlink.enums["MAV_RESULT"][result].name
            (self.log.event if ok else self.log.warning)(
                "message_interval", name, hz=hz, accepted=ok, result=result_name)
        return results

    def statustext(self, text, severity=mavlink.MAV_SEVERITY_INFO):
        """STATUSTEXT to the ground station, split into 50-char messages."""
        text = STATUSTEXT_PREFIX + text
        chunks = [text[i:i + STATUSTEXT_MAX] for i in range(0, len(text), STATUSTEXT_MAX)]
        for chunk in chunks:
            self.send(self.master.mav.statustext_encode(severity, chunk.encode("ascii", "replace")))

    def read_param(self, name, timeout_s=None, retries=None):
        """Read one FC parameter by name (read-only). Returns its value, or None."""
        c = self.cfg.connection
        timeout_s = c.param_read_timeout_s if timeout_s is None else timeout_s
        retries = c.param_read_retries if retries is None else retries
        for _ in range(retries):
            msg = self.master.mav.param_request_read_encode(
                self.sysid, MAV_COMP_ID_AUTOPILOT1, name.encode("ascii"), -1)
            reply = self._wait_for(self._param_waiters, name, lambda: self.send(msg, log=False), timeout_s)
            if reply:
                return float(reply.param_value)
        return None

    def request_mode(self, mode, timeout_s=None):
        """Change flight mode. The ModeWatcher is told first so the change counts as
        ours. Returns True once HEARTBEAT shows the mode. Blocked in shadow mode,
        after a foreign mode change, and always for RTL."""
        timeout_s = self.cfg.commands.mode_change_timeout_s if timeout_s is None else timeout_s
        if mode not in COPTER_MODES:
            raise ValueError(f"unknown copter mode {mode}")
        msg = self.master.mav.command_long_encode(
            self.sysid, MAV_COMP_ID_AUTOPILOT1, mavlink.MAV_CMD_DO_SET_MODE, 0,
            mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, COPTER_MODES[mode], 0, 0, 0, 0, 0)
        reason = self.gate_reason(msg)
        if reason is not None:
            self.log.command("COMMAND_LONG", f"blocked: {reason}", **_describe(msg))
            return False
        if not self.watcher.expect(mode, timeout_s):
            self.log.event("mode_request", f"already in {mode}")
            return True
        ack = self._wait_for(self._ack_waiters, mavlink.MAV_CMD_DO_SET_MODE, lambda: self.send(msg),
                             self.cfg.connection.command_ack_timeout_s)
        if ack is False:
            self.watcher.cancel_expectation()
            return False
        if ack is None or ack.result != mavlink.MAV_RESULT_ACCEPTED:
            self.watcher.cancel_expectation()
            self.log.warning("mode_request", f"{mode} not accepted",
                             result=None if ack is None else mavlink.enums["MAV_RESULT"][ack.result].name)
            return False
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.watcher.mode == mode:
                return True
            time.sleep(0.05)
        return False

    def _on_foreign_mode(self, old, new, tripped):
        if tripped:
            self.statustext(f"mode {old}->{new} not mine: stopped",
                            mavlink.MAV_SEVERITY_CRITICAL)
        else:
            self.statustext(f"mode {old}->{new} not mine (shadow)", mavlink.MAV_SEVERITY_WARNING)
