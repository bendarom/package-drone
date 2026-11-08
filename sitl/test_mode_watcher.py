"""SITL ONLY: prove the mode watcher catches mode changes this code didn't make.
No arming; the vehicle stays disarmed on the ground throughout.

  (a) our own request_mode(ALT_HOLD) is accepted, watcher not tripped
  (b) mode_poke (second connection) -> LOITER: watcher trips, STATUSTEXT sent,
      later control messages are blocked and logged as blocked
  (c) shadow mode: a foreign change is logged only, never trips; control blocked

Needs SITL running (docs/SITL.md). Exit code 0 only if every check holds.

  python sitl/test_mode_watcher.py
"""

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "sitl"))

from config import load_config, with_overrides  # noqa: E402
from mav.connection import MavLink  # noqa: E402
from mav.log import open_run_log  # noqa: E402
from mode_poke import poke  # noqa: E402

OVERLAY = REPO_ROOT / "sitl" / "config.sitl.yaml"
failures = []


def check(cond, what):
    print(f"{'ok  ' if cond else 'FAIL'} {what}")
    if not cond:
        failures.append(what)


def wait_until(fn, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(0.05)
    return False


def zero_velocity(link):
    """A harmless control message (zero body-frame velocity) to probe the gate."""
    m = link.master.mav
    return m.set_position_target_local_ned_encode(
        0, link.sysid, 1, 8, 0b0000111111000111, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)  # MAV_FRAME_BODY_NED


def events(log):
    with open(log.dir / "events.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def wait_position_ready(link):
    """LOITER needs a GPS position, even disarmed."""
    t = link.telemetry
    check(wait_until(lambda: (t.gps_fix_type or 0) >= 3 and t.ekf_ok, 90), "GPS 3D fix and EKF ok (needed for LOITER)")


def real_mode_run(cfg):
    log = open_run_log(cfg, run_name=time.strftime("%Y%m%d-%H%M%S") + "-modewatch-sitl")
    link = MavLink(cfg, log).connect()
    try:
        link.set_message_intervals()
        check(wait_until(lambda: link.watcher.mode is not None, 5), f"baseline mode seen ({link.watcher.mode})")
        wait_position_ready(link)

        # (a) our own change
        check(link.request_mode("ALT_HOLD"), "(a) request_mode(ALT_HOLD) reached ALT_HOLD")
        time.sleep(1.5)
        check(not link.watcher.tripped and not link.watcher.foreign_changes,
              "(a) own mode change not flagged as foreign")

        # (b) foreign change from a second connection
        check(poke("LOITER"), "(b) second connection switched to LOITER")
        check(wait_until(lambda: link.watcher.tripped, 5), "(b) watcher tripped")
        check(link.watcher.trip_reason == "ALT_HOLD -> LOITER", f"(b) trip reason {link.watcher.trip_reason!r}")
        check(link.request_mode("ALT_HOLD") is False, "(b) request_mode blocked after trip")
        check(link.send(zero_velocity(link)) is False, "(b) velocity command blocked after trip")
        time.sleep(1.5)
        check(link.telemetry.mode == "LOITER", "(b) vehicle still in LOITER (we didn't change it back)")
    finally:
        link.close()
        log.close()

    ev = events(log)
    check(any(e.get("kind") == "mode_change_foreign" and e.get("new") == "LOITER" for e in ev),
          "(b) foreign mode change in events.jsonl")
    check(any(e.get("type") == "command" and e.get("name") == "STATUSTEXT" and e.get("status") == "sent"
              and "not mine" in e.get("text", "") for e in ev), "(b) STATUSTEXT sent")
    blocked = [e for e in ev if e.get("type") == "command" and str(e.get("status")).startswith("blocked")]
    check(len(blocked) >= 2, f"(b) blocked commands logged ({len(blocked)})")
    check(any(e.get("kind") == "mode_change_ours" for e in ev), "(a) own mode change logged")
    return log.dir


def shadow_run(cfg):
    cfg = with_overrides(cfg, {"connection": {"run_mode": "shadow"}})
    log = open_run_log(cfg, run_name=time.strftime("%Y%m%d-%H%M%S") + "-modewatch-shadow")
    link = MavLink(cfg, log).connect()
    try:
        check(wait_until(lambda: link.watcher.mode is not None, 5), f"(c) baseline mode seen ({link.watcher.mode})")
        check(link.request_mode("ALT_HOLD") is False, "(c) shadow: request_mode blocked")
        check(poke("ALT_HOLD"), "(c) second connection switched to ALT_HOLD")
        check(wait_until(lambda: link.watcher.foreign_changes, 5), "(c) shadow: foreign change seen")
        check(not link.watcher.tripped, "(c) shadow: watcher not tripped (log only)")
    finally:
        link.close()
        log.close()
    ev = events(log)
    check(any(e.get("kind") == "mode_change_foreign" and e.get("shadow") for e in ev),
          "(c) shadow foreign change in events.jsonl")
    return log.dir


def main():
    cfg = load_config(overlay=OVERLAY)
    dirs = [real_mode_run(cfg), shadow_run(cfg)]
    poke("STABILIZE")  # leave SITL as we found it
    print("logs:", *dirs, sep="\n  ")
    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
