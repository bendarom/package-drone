"""Flags every flight-mode change this code didn't make.

Hard rule (CLAUDE.md): if the mode changes and this code didn't change it, stop
sending all commands immediately and never switch modes again. The watcher latches
`tripped`; the connection's send gate checks it before every control message.
Shadow mode only logs: the code never has control, so there is nothing to stop.

Our own mode changes go through expect() first, which opens a window in which a
change to exactly that mode counts as ours. Anything else is foreign: a pilot
switch, an ArduPilot failsafe (RTL, LAND), or another GCS.
"""

import threading
import time
from dataclasses import dataclass


@dataclass
class _Expectation:
    mode: str
    deadline: float


class ModeWatcher:
    def __init__(self, log, shadow=False, clock=time.monotonic):
        self._log = log
        self.shadow = shadow
        self._clock = clock
        self._lock = threading.Lock()
        self._callbacks = []
        self._expect = None
        self.mode = None          # last mode seen in HEARTBEAT
        self.armed = None
        self.tripped = False      # latched; never cleared
        self.trip_reason = None
        self.foreign_changes = []  # (old, new, t) for every foreign change, tripped or not

    def add_callback(self, fn):
        """fn(old_mode, new_mode, tripped) is called after every foreign change."""
        self._callbacks.append(fn)

    def expect(self, mode, timeout_s):
        """Call right before sending our own mode change. Returns False if the
        vehicle is already in that mode (nothing to send)."""
        with self._lock:
            if self.tripped:
                raise RuntimeError("mode watcher tripped: this code must not change modes again")
            if self.mode == mode:
                return False
            self._expect = _Expectation(mode, self._clock() + timeout_s)
            return True

    def cancel_expectation(self):
        with self._lock:
            self._expect = None

    @property
    def pending(self):
        with self._lock:
            return None if self._expect is None else self._expect.mode

    def on_heartbeat(self, mode, armed, now=None):
        """Feed every vehicle HEARTBEAT (decoded mode name and armed flag)."""
        now = self._clock() if now is None else now
        foreign = None
        with self._lock:
            if self._expect is not None and now > self._expect.deadline and mode != self._expect.mode:
                self._log.warning("mode_change_not_seen",
                                  f"requested {self._expect.mode} not seen in HEARTBEAT in time",
                                  requested=self._expect.mode, mode=mode)
                self._expect = None

            if self.armed is not None and armed != self.armed:
                self._log.event("armed" if armed else "disarmed", f"vehicle {'armed' if armed else 'disarmed'}",
                                mode=mode)
            self.armed = armed

            if self.mode is None:
                self.mode = mode
                self._log.event("mode_baseline", f"initial mode {mode}", mode=mode, armed=armed)
                return
            if mode == self.mode:
                return

            old = self.mode
            self.mode = mode
            if self._expect is not None and mode == self._expect.mode and now <= self._expect.deadline:
                self._expect = None
                self._log.event("mode_change_ours", f"{old} -> {mode} (requested by this code)",
                                old=old, new=mode)
                return

            self._expect = None
            self.foreign_changes.append((old, mode, now))
            if self.shadow:
                self._log.warning("mode_change_foreign", f"{old} -> {mode} not made by this code (shadow: log only)",
                                  old=old, new=mode, shadow=True)
            else:
                first = not self.tripped
                self.tripped = True
                if first:
                    self.trip_reason = f"{old} -> {mode}"
                self._log.error("mode_change_foreign",
                                f"{old} -> {mode} not made by this code: all commands stopped for good",
                                old=old, new=mode, first_trip=first)
            foreign = (old, mode, self.tripped)

        for fn in self._callbacks:
            try:
                fn(*foreign)
            except Exception as e:  # a callback failing must not hide the trip
                self._log.error("mode_watcher_callback_failed", repr(e))
