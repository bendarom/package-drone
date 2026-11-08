"""Run logs in logs/<YYYYmmdd-HHMMSS>/.

events.jsonl: one JSON object per line for every event, command sent (or blocked),
parameter-check result, mode change and decision. telemetry.jsonl: periodic
telemetry snapshots. Every line has t_utc (ISO 8601) and t_mono (time.monotonic(),
for intervals). Lines are flushed as written so a crash or power cut keeps
everything up to the last line.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

console = logging.getLogger("drone")


def _setup_console():
    if not console.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        console.addHandler(h)
        console.setLevel(logging.INFO)
        console.propagate = False


def _jsonable(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace").rstrip("\x00")
    return str(v)


class RunLog:
    def __init__(self, log_dir, run_name=None, console_output=True):
        if console_output:
            _setup_console()
        self.console_output = console_output
        run_name = run_name or datetime.now().strftime("%Y%m%d-%H%M%S")
        base = Path(log_dir)
        self.dir = base / run_name
        n = 1
        while self.dir.exists():  # two runs in the same second
            n += 1
            self.dir = base / f"{run_name}-{n}"
        self.dir.mkdir(parents=True)
        self._lock = threading.Lock()
        self._events = open(self.dir / "events.jsonl", "a", encoding="utf-8")
        self._telemetry = open(self.dir / "telemetry.jsonl", "a", encoding="utf-8")

    def _write(self, f, record):
        record = {
            "t_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "t_mono": round(time.monotonic(), 4),
            **_jsonable(record),
        }
        line = json.dumps(record, separators=(",", ":"))
        with self._lock:
            if f.closed:
                return
            f.write(line + "\n")
            f.flush()

    def event(self, kind, msg="", level=logging.INFO, **fields):
        """Something happened (state change, decision, mode change, link loss...)."""
        self._write(self._events, {"type": "event", "kind": kind, "msg": msg, **fields})
        if self.console_output:
            extra = " ".join(f"{k}={v}" for k, v in fields.items())
            console.log(level, f"[{kind}] {msg} {extra}".rstrip())

    def warning(self, kind, msg="", **fields):
        self.event(kind, msg, level=logging.WARNING, **fields)

    def error(self, kind, msg="", **fields):
        self.event(kind, msg, level=logging.ERROR, **fields)

    def command(self, name, status, **fields):
        """A message we sent (status 'sent') or refused to send ('blocked: <why>')."""
        self._write(self._events, {"type": "command", "name": name, "status": status, **fields})
        if self.console_output:
            level = logging.WARNING if status != "sent" else logging.DEBUG
            console.log(level, f"[command] {name} {status} {fields}")

    def telemetry(self, snapshot):
        self._write(self._telemetry, {"type": "telemetry", **snapshot})

    def close(self):
        with self._lock:
            self._events.close()
            self._telemetry.close()


def open_run_log(cfg, run_name=None, console_output=True):
    """RunLog under config logging.dir (repo-relative unless absolute)."""
    from config import resolve_path
    return RunLog(resolve_path(cfg.logging.dir), run_name, console_output)
