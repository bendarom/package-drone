import pytest

from mav.mode_watcher import ModeWatcher


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


def make(fake_log, clock, shadow=False):
    w = ModeWatcher(fake_log, shadow=shadow, clock=clock)
    calls = []
    w.add_callback(lambda old, new, tripped: calls.append((old, new, tripped)))
    w.on_heartbeat("STABILIZE", False)
    return w, calls


def test_first_heartbeat_is_baseline(fake_log, clock):
    w, calls = make(fake_log, clock)
    assert w.mode == "STABILIZE" and not w.tripped and calls == []
    assert "mode_baseline" in fake_log.kinds()


def test_expected_change_accepted(fake_log, clock):
    w, calls = make(fake_log, clock)
    assert w.expect("GUIDED", 3.0)
    clock.t += 1
    w.on_heartbeat("GUIDED", False)
    assert not w.tripped and calls == []
    assert "mode_change_ours" in fake_log.kinds()
    assert w.pending is None


def test_foreign_change_trips_and_latches(fake_log, clock):
    w, calls = make(fake_log, clock)
    w.on_heartbeat("LOITER", False)
    assert w.tripped and w.trip_reason == "STABILIZE -> LOITER"
    assert calls == [("STABILIZE", "LOITER", True)]
    # Back to the old mode: still tripped, reason unchanged, second change also reported.
    w.on_heartbeat("STABILIZE", False)
    assert w.tripped and w.trip_reason == "STABILIZE -> LOITER"
    assert len(calls) == 2
    with pytest.raises(RuntimeError):
        w.expect("GUIDED", 3.0)


def test_change_to_different_mode_than_expected_is_foreign(fake_log, clock):
    w, calls = make(fake_log, clock)
    w.expect("GUIDED", 3.0)
    w.on_heartbeat("RTL", False)   # e.g. an ArduPilot failsafe beat us to it
    assert w.tripped and calls[0][1] == "RTL"
    assert w.pending is None


def test_stale_expectation_does_not_cover_late_change(fake_log, clock):
    w, calls = make(fake_log, clock)
    w.expect("GUIDED", 3.0)
    clock.t += 5
    w.on_heartbeat("STABILIZE", False)   # deadline passed, mode never changed
    assert "mode_change_not_seen" in fake_log.kinds()
    w.on_heartbeat("GUIDED", False)      # someone else switches to GUIDED later
    assert w.tripped


def test_expect_same_mode_returns_false(fake_log, clock):
    w, _ = make(fake_log, clock)
    assert w.expect("STABILIZE", 3.0) is False
    assert w.pending is None


def test_shadow_logs_only(fake_log, clock):
    w, calls = make(fake_log, clock, shadow=True)
    w.on_heartbeat("LOITER", False)
    assert not w.tripped
    assert calls == [("STABILIZE", "LOITER", False)]
    assert w.foreign_changes and w.foreign_changes[0][:2] == ("STABILIZE", "LOITER")
    warn = [r for r in fake_log.records if r[1] == "mode_change_foreign"]
    assert warn[0][0] == "warning" and warn[0][3]["shadow"] is True


def test_arm_disarm_logged(fake_log, clock):
    w, _ = make(fake_log, clock)
    w.on_heartbeat("STABILIZE", True)
    w.on_heartbeat("STABILIZE", False)
    assert fake_log.kinds().count("armed") == 1
    assert fake_log.kinds().count("disarmed") == 1
    assert not w.tripped


def test_failing_callback_does_not_hide_trip(fake_log, clock):
    w = ModeWatcher(fake_log, clock=clock)
    w.add_callback(lambda *a: 1 / 0)
    w.on_heartbeat("STABILIZE", False)
    w.on_heartbeat("LAND", False)
    assert w.tripped
    assert "mode_watcher_callback_failed" in fake_log.kinds()
