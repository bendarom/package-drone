"""Startup parameter check against params/expected_<real|sitl>.yaml (docs/PARAMS.md).

Read-only: each parameter is read with PARAM_REQUEST_READ. This module never sends
PARAM_SET, and the connection's send gate blocks parameter writes anyway.

Result per entry:
  PASS     actual value matches
  FAIL     actual value doesn't match (the entry's reason says why it matters)
  MISSING  no PARAM_VALUE reply (wrong name for this firmware, or link trouble)
  TBD      expected value is still null in the file: can't be checked yet
The check passes only if every entry is PASS.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

PARAMS_DIR = Path(__file__).resolve().parent.parent / "params"
OPS = ("eq", "ge", "le", "bits_set")
FLOAT_EPS = 1e-5   # PARAM_VALUE is float32: 0.1 comes back as 0.100000001...

PASS, FAIL, MISSING, TBD = "PASS", "FAIL", "MISSING", "TBD"


class ParamFileError(Exception):
    pass


@dataclass(frozen=True)
class Expected:
    name: str
    value: float          # None = TBD
    tolerance: float
    op: str
    reason: str


@dataclass(frozen=True)
class Result:
    expected: Expected
    status: str
    actual: float = None

    def describe(self):
        e = self.expected
        want = "TBD" if e.value is None else _fmt_expectation(e)
        got = "no reply" if self.actual is None else f"{self.actual:g}"
        return f"{self.status:<7} {e.name:<18} expected {want:<14} got {got:<10} ({e.reason})"


def _fmt_expectation(e):
    v = f"{e.value:g}"
    if e.op == "eq":
        return v if e.tolerance == 0 else f"{v} ±{e.tolerance:g}"
    return {"ge": f">= {v}", "le": f"<= {v}", "bits_set": f"bits {int(e.value)} set"}[e.op]


@dataclass
class Report:
    file: str
    results: list

    @property
    def ok(self):
        return bool(self.results) and all(r.status == PASS for r in self.results)

    def count(self, status):
        return sum(r.status == status for r in self.results)

    def summary(self):
        counts = ", ".join(f"{s} {self.count(s)}" for s in (PASS, FAIL, MISSING, TBD))
        return f"parameter check {'PASSED' if self.ok else 'FAILED'} ({self.file}): {counts}"


def expected_file(run_mode, params_dir=PARAMS_DIR):
    """sitl -> expected_sitl.yaml; real and shadow -> expected_real.yaml."""
    return Path(params_dir) / ("expected_sitl.yaml" if run_mode == "sitl" else "expected_real.yaml")


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_expected(data, source="<expected params>"):
    """Validate the YAML structure and return a list of Expected."""
    problems, entries, seen = [], [], set()
    items = data.get("params") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ParamFileError(f"{source}: top level must have a 'params:' list")
    for i, item in enumerate(items):
        where = f"{source} params[{i}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: expected a map")
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name or name != name.upper() or len(name) > 16:
            problems.append(f"{where}: name must be an upper-case parameter name (<= 16 chars), got {name!r}")
            continue
        where = f"{source} {name}"
        unknown = set(item) - {"name", "value", "tolerance", "op", "reason"}
        if unknown:
            problems.append(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
        if name in seen:
            problems.append(f"{where}: listed twice")
        seen.add(name)
        value = item.get("value")
        if value is not None and not _is_num(value):
            problems.append(f"{where}: value must be a number or null (TBD), got {value!r}")
        tol = item.get("tolerance", 0)
        if not _is_num(tol) or tol < 0:
            problems.append(f"{where}: tolerance must be a number >= 0, got {tol!r}")
        op = item.get("op", "eq")
        if op not in OPS:
            problems.append(f"{where}: op must be one of {', '.join(OPS)}, got {op!r}")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            problems.append(f"{where}: reason is required")
        if not problems:
            entries.append(Expected(name, None if value is None else float(value), float(tol), op, reason))
    if problems:
        raise ParamFileError("\n".join(problems))
    return entries


def load_expected(run_mode, params_dir=PARAMS_DIR):
    path = expected_file(run_mode, params_dir)
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise ParamFileError(f"{path}: file not found") from None
    except yaml.YAMLError as e:
        raise ParamFileError(f"{path}: YAML syntax error: {e}") from None
    return path, parse_expected(data, path.name)


def compare(expected, actual):
    """Status for one entry given the value read from the FC (None = no reply)."""
    if expected.value is None:
        return TBD
    if actual is None:
        return MISSING
    v, tol = expected.value, expected.tolerance + FLOAT_EPS * max(1.0, abs(expected.value))
    if expected.op == "eq":
        ok = abs(actual - v) <= tol
    elif expected.op == "ge":
        ok = actual >= v - tol
    elif expected.op == "le":
        ok = actual <= v + tol
    else:  # bits_set
        ok = (int(round(actual)) & int(v)) == int(v)
    return PASS if ok else FAIL


def check_params(read_fn, entries, log=None, file="<expected params>"):
    """Read every entry with read_fn(name) -> float|None and compare.
    TBD entries are still read so the report shows the FC's current value."""
    results = []
    for e in entries:
        actual = read_fn(e.name)
        r = Result(e, compare(e, actual), actual)
        results.append(r)
        if log is not None:
            fields = dict(name=e.name, status=r.status, expected=e.value, op=e.op,
                          tolerance=e.tolerance, actual=actual, reason=e.reason)
            if r.status == PASS:
                log.event("param_check", r.describe(), **fields)
            else:
                log.warning("param_check", r.describe(), **fields)
    report = Report(str(file), results)
    if log is not None:
        (log.event if report.ok else log.error)("param_check_summary", report.summary(), ok=report.ok)
    return report


def run_param_check(link, log, params_dir=PARAMS_DIR):
    """Check the connected FC against the file for its run_mode."""
    path, entries = load_expected(link.run_mode, params_dir)
    log.event("param_check_start", f"{len(entries)} parameters from {path.name}", run_mode=link.run_mode)
    return check_params(link.read_param, entries, log, path.name)
