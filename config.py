"""Load and validate config.yaml.

Every key in config.yaml is listed in SCHEMA with its type, range and level:
- CONNECT: needed to talk to the FC at all (tools, shadow, mission). Never null.
- MISSION: needed to fly. May be null (TBD) at connect level; must be set at mission level.
- OPTIONAL: may stay null (e.g. exposure_time_us in auto exposure).

validate() collects every problem and load_config() raises one ConfigError listing
all of them, so a bad file is fixed in one pass instead of one error at a time.
"""

import copy
import math
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = REPO_ROOT / "config.yaml"

CONNECT = "connect"
MISSION = "mission"
OPTIONAL = "optional"

RUN_MODES = ("real", "sitl", "shadow")
MIN_VELOCITY_RATE_HZ = 5.0       # MISSION.md: velocity commands streamed at >= 5 Hz
CONTACT_HEIGHT_MARGIN_M = 0.05   # MISSION.md: contact_height_max_m formula
MIN_TAG_PX_AT_SEARCH = 30        # MISSION.md: tag must span >= ~30 px at search height


class ConfigError(Exception):
    """Raised with one line per problem found in the config."""

    def __init__(self, problems, source="config.yaml"):
        self.problems = list(problems)
        lines = "\n".join(f"  - {p}" for p in self.problems)
        super().__init__(f"{source}: {len(self.problems)} problem(s):\n{lines}")


@dataclass(frozen=True)
class Spec:
    kind: str                 # num | int | str | choice | vec | rates
    level: str = MISSION
    gt: float = None          # value must be > gt
    ge: float = None          # value must be >= ge
    le: float = None          # value must be <= le
    choices: tuple = ()
    length: int = None        # for vec


def _pos(level=MISSION, kind="num"):
    return Spec(kind, level, gt=0)


SCHEMA = {
    "connection": {
        "connection_string": Spec("str", CONNECT),
        "baud": _pos(CONNECT, "int"),
        "sysid": Spec("int", CONNECT, ge=1, le=255),
        "compid": Spec("int", CONNECT, ge=1, le=255),
        "run_mode": Spec("choice", CONNECT, choices=RUN_MODES),
        "heartbeat_hz": _pos(CONNECT),
        "connect_timeout_s": _pos(CONNECT),
        "link_timeout_s": _pos(CONNECT),
        "command_ack_timeout_s": _pos(CONNECT),
        "param_read_timeout_s": _pos(CONNECT),
        "param_read_retries": Spec("int", CONNECT, ge=1),
    },
    "telemetry": {
        "rates_hz": Spec("rates", CONNECT),
        "log_hz": _pos(CONNECT),
    },
    "commands": {
        "velocity_rate_hz": _pos(),
        "mode_change_timeout_s": _pos(),
    },
    "start_switch": {
        "rc_channel": Spec("int", ge=1, le=18),
        "pwm_threshold": Spec("int", ge=800, le=2200),
    },
    "positions": {
        "box_lat": Spec("num", ge=-90, le=90),
        "box_lon": Spec("num", ge=-180, le=180),
        "box_ground_alt_rel_home_m": Spec("num"),
    },
    "altitudes": {
        "takeoff_check_height_m": _pos(),
        "takeoff_check_tolerance_m": _pos(),
        "cruise_alt_rel_home_m": _pos(),
        "search_height_m": _pos(),
        "commit_height_m": _pos(),
        "pickup_check_height_m": _pos(),
        "balcony_approach_alt_rel_home_m": _pos(),
        "balcony_handoff_height_m": _pos(),
    },
    "speeds": {
        "cruise_speed_m_s": _pos(),
        "descent_speed_m_s": _pos(),
        "final_descent_speed_m_s": _pos(),
        "max_centering_speed_m_s": _pos(),
        "centering_tolerance_m": _pos(),
    },
    "search": {
        "search_leg_spacing_m": _pos(),
        "search_max_radius_m": _pos(),
        "search_speed_m_s": _pos(),
        "tag_acquire_frames": _pos(kind="int"),
    },
    "geometry": {
        "camera_offset_m": Spec("vec", length=3),
        "lidar_offset_m": Spec("vec", length=3),
        "lidar_mount_height_m": _pos(),
        "box_thickness_m": _pos(),
        "magnet_clearance_m": Spec("num", ge=0),
    },
    "tags": {
        "family": Spec("choice", choices=("tag36h11",)),
        "box_tag_id": Spec("int", ge=0),
        "balcony_tag_id": Spec("int", ge=0),
        "tag_size_m": _pos(),
    },
    "camera": {
        "resolution": Spec("vec", length=2),
        "fov_deg": Spec("vec", length=2),
        "frame_rate": _pos(),
        "exposure_mode": Spec("choice", choices=("auto", "cap", "fixed")),
        "exposure_time_us": Spec("int", OPTIONAL, gt=0),
        "calibration_file": Spec("str", OPTIONAL),
    },
    "vision": {
        "source": Spec("choice", choices=("camera", "files", "sim")),
    },
    "rangefinder": {
        "min_valid_m": _pos(CONNECT),
        "max_reliable_m": _pos(CONNECT),
        "preflight_tolerance_m": _pos(),
        "preflight_max_over_m": _pos(),
        "baro_lidar_warn_m": _pos(),
    },
    "pickup": {
        "contact_stall_s": _pos(),
        "contact_stall_vz_m_s": _pos(),
        "magnet_settle_s": Spec("num", ge=0),
        "pickup_check_hold_s": _pos(),
        "attach_throttle_rise_pct": Spec("num"),
    },
    "timeouts": {
        "takeoff_climb_timeout_s": _pos(),
        "search_timeout_s": _pos(),
        "tag_lost_hold_s": _pos(),
        "reacquire_timeout_s": _pos(),
        "approach_timeout_s": _pos(),
        "descent_timeout_s": _pos(),
        "balcony_tag_timeout_s": _pos(),
        "mission_timeout_s": _pos(),
    },
    "battery_gps": {
        "min_start_v": _pos(),
        "return_v": _pos(),
        "min_sats": _pos(kind="int"),
    },
    "logging": {
        "dir": Spec("str", CONNECT),
    },
}


class Section:
    """Read-only attribute access to one config section."""

    def __init__(self, name, values):
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_values", dict(values))

    def __getattr__(self, key):
        try:
            return self._values[key]
        except KeyError:
            raise AttributeError(f"config has no key {self._name}.{key}") from None

    def __setattr__(self, key, value):
        raise AttributeError("config is read-only")

    def as_dict(self):
        return copy.deepcopy(self._values)


class Config:
    """Validated config: cfg.<section>.<key>, plus derived values and warnings."""

    def __init__(self, raw, derived, warnings, level):
        self.raw = raw
        self.derived = derived
        self.warnings = warnings
        self.level = level
        for name, values in raw.items():
            setattr(self, name, Section(name, values))

    @property
    def run_mode(self):
        return self.connection.run_mode


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_value(path, spec, v):
    """Type/range problems for one non-null value."""
    if spec.kind in ("num", "int"):
        if spec.kind == "int" and not (isinstance(v, int) and not isinstance(v, bool)):
            return [f"{path}: expected an integer, got {v!r}"]
        if not _is_num(v) or not math.isfinite(v):
            return [f"{path}: expected a number, got {v!r}"]
        if spec.gt is not None and not v > spec.gt:
            return [f"{path}: must be > {spec.gt}, got {v}"]
        if spec.ge is not None and not v >= spec.ge:
            return [f"{path}: must be >= {spec.ge}, got {v}"]
        if spec.le is not None and not v <= spec.le:
            return [f"{path}: must be <= {spec.le}, got {v}"]
        return []
    if spec.kind == "str":
        if not isinstance(v, str) or not v.strip():
            return [f"{path}: expected a non-empty string, got {v!r}"]
        return []
    if spec.kind == "choice":
        if v not in spec.choices:
            return [f"{path}: must be one of {', '.join(map(str, spec.choices))}, got {v!r}"]
        return []
    if spec.kind == "vec":
        if not isinstance(v, list) or len(v) != spec.length or not all(_is_num(x) for x in v):
            return [f"{path}: expected a list of {spec.length} numbers, got {v!r}"]
        return []
    if spec.kind == "rates":
        if not isinstance(v, dict) or not v:
            return [f"{path}: expected a map of MAVLink message name -> Hz, got {v!r}"]
        problems = []
        for msg, hz in v.items():
            if not isinstance(msg, str) or not msg.isupper():
                problems.append(f"{path}.{msg}: message names are upper case, e.g. ATTITUDE")
            if not _is_num(hz) or not hz > 0:
                problems.append(f"{path}.{msg}: rate must be a number > 0 Hz, got {hz!r}")
        return problems
    raise ValueError(f"bad spec kind {spec.kind}")


def _get(raw, section, key):
    return (raw.get(section) or {}).get(key)


def _cross_checks(raw):
    """Problems and warnings that involve more than one key. Skips any check whose
    inputs are null (the TBD check reports those) or of the wrong type."""
    problems, warnings = [], []

    def num(section, key):
        v = _get(raw, section, key)
        return v if _is_num(v) else None

    clearance, thickness = num("geometry", "magnet_clearance_m"), num("geometry", "box_thickness_m")
    if clearance is not None and thickness is not None and clearance > thickness:
        problems.append(
            f"geometry.magnet_clearance_m ({clearance}) > geometry.box_thickness_m ({thickness}): "
            "the magnet could never reach the box")

    commit = num("altitudes", "commit_height_m")
    pickup = num("altitudes", "pickup_check_height_m")
    search = num("altitudes", "search_height_m")
    if None not in (commit, pickup, search) and not commit < pickup < search:
        problems.append(
            "altitudes: need commit_height_m < pickup_check_height_m < search_height_m, "
            f"got {commit} / {pickup} / {search}")

    cruise = num("altitudes", "cruise_alt_rel_home_m")
    box_ground = num("positions", "box_ground_alt_rel_home_m")
    if cruise is not None and box_ground is not None and search is not None:
        search_alt = box_ground + search
        if not search_alt < cruise:
            problems.append(
                f"altitudes: search altitude rel. home (box_ground_alt_rel_home_m + search_height_m = "
                f"{search_alt:g}) must be below cruise_alt_rel_home_m ({cruise})")
    takeoff = num("altitudes", "takeoff_check_height_m")
    if cruise is not None and takeoff is not None and not takeoff < cruise:
        problems.append(f"altitudes: takeoff_check_height_m ({takeoff}) must be below cruise_alt_rel_home_m ({cruise})")
    approach = num("altitudes", "balcony_approach_alt_rel_home_m")
    handoff = num("altitudes", "balcony_handoff_height_m")
    if cruise is not None and approach is not None and not approach <= cruise:
        problems.append(
            f"altitudes: balcony_approach_alt_rel_home_m ({approach}) must not be above cruise_alt_rel_home_m ({cruise})")
    if approach is not None and handoff is not None and not handoff < approach:
        problems.append(
            f"altitudes: balcony_handoff_height_m ({handoff}) must be below balcony_approach_alt_rel_home_m ({approach})")

    run_mode = _get(raw, "connection", "run_mode")
    if run_mode == "sitl" and box_ground is not None and box_ground != 0:
        problems.append(
            f"positions.box_ground_alt_rel_home_m must be 0 in SITL (flat ground), got {box_ground}")

    vel_rate = num("commands", "velocity_rate_hz")
    if vel_rate is not None and vel_rate < MIN_VELOCITY_RATE_HZ:
        problems.append(f"commands.velocity_rate_hz must be >= {MIN_VELOCITY_RATE_HZ:g} Hz, got {vel_rate}")

    rmin, rmax = num("rangefinder", "min_valid_m"), num("rangefinder", "max_reliable_m")
    if rmin is not None and rmax is not None and not rmin < rmax:
        problems.append(f"rangefinder: min_valid_m ({rmin}) must be below max_reliable_m ({rmax})")

    start_v, return_v = num("battery_gps", "min_start_v"), num("battery_gps", "return_v")
    if start_v is not None and return_v is not None and not return_v < start_v:
        problems.append(f"battery_gps: return_v ({return_v}) must be below min_start_v ({start_v})")

    box_id, balcony_id = _get(raw, "tags", "box_tag_id"), _get(raw, "tags", "balcony_tag_id")
    if box_id is not None and box_id == balcony_id:
        problems.append(f"tags: box_tag_id and balcony_tag_id are both {box_id}")

    exposure_mode = _get(raw, "camera", "exposure_mode")
    if exposure_mode in ("cap", "fixed") and _get(raw, "camera", "exposure_time_us") is None:
        problems.append(f"camera.exposure_time_us is required when exposure_mode is {exposure_mode}")

    warnings.extend(_tag_size_warnings(raw))
    return problems, warnings


def tag_pixels(tag_size_m, height_m, resolution, fov_deg):
    """(width_px, height_px) a tag of tag_size_m spans when the camera is height_m
    above it, from the nominal FOV (pinhole, camera pointing straight down)."""
    footprint_w = 2 * height_m * math.tan(math.radians(fov_deg[0]) / 2)
    footprint_h = 2 * height_m * math.tan(math.radians(fov_deg[1]) / 2)
    return tag_size_m / footprint_w * resolution[0], tag_size_m / footprint_h * resolution[1]


def _tag_size_warnings(raw):
    size = _get(raw, "tags", "tag_size_m")
    res, fov = _get(raw, "camera", "resolution"), _get(raw, "camera", "fov_deg")
    search, commit = _get(raw, "altitudes", "search_height_m"), _get(raw, "altitudes", "commit_height_m")
    if not all(_is_num(v) and v > 0 for v in (size, search, commit)):
        return []
    if not all(isinstance(v, list) and len(v) == 2 and all(_is_num(x) and x > 0 for x in v) for v in (res, fov)):
        return []
    warnings = []
    px_w, px_h = tag_pixels(size, search, res, fov)
    if min(px_w, px_h) < MIN_TAG_PX_AT_SEARCH:
        warnings.append(
            f"tags.tag_size_m {size} m spans only ~{min(px_w, px_h):.0f} px at search_height_m {search} m "
            f"(need >= {MIN_TAG_PX_AT_SEARCH} px)")
    px_w, px_h = tag_pixels(size, commit, res, fov)
    if px_w >= res[0] or px_h >= res[1]:
        warnings.append(
            f"tags.tag_size_m {size} m doesn't fit in the frame at commit_height_m {commit} m "
            f"(~{px_w:.0f}x{px_h:.0f} px vs {res[0]}x{res[1]})")
    return warnings


def derive(raw):
    """Values computed from config (never set in the file). None while inputs are TBD."""
    thickness = _get(raw, "geometry", "box_thickness_m")
    clearance = _get(raw, "geometry", "magnet_clearance_m")
    box_ground = _get(raw, "positions", "box_ground_alt_rel_home_m")
    search = _get(raw, "altitudes", "search_height_m")
    derived = {"contact_height_max_m": None, "search_alt_rel_home_m": None}
    if _is_num(thickness) and _is_num(clearance):
        derived["contact_height_max_m"] = (thickness - clearance) + CONTACT_HEIGHT_MARGIN_M
    if _is_num(box_ground) and _is_num(search):
        derived["search_alt_rel_home_m"] = box_ground + search
    return derived


def validate(raw, level=CONNECT):
    """Return (problems, warnings) for a raw config dict at the given level."""
    if level not in (CONNECT, MISSION):
        raise ValueError(f"level must be {CONNECT!r} or {MISSION!r}")
    if not isinstance(raw, dict):
        return [f"top level must be a map of sections, got {type(raw).__name__}"], []

    problems = []
    for section in raw:
        if section not in SCHEMA:
            problems.append(f"{section}: unknown section")
    for section, keys in SCHEMA.items():
        values = raw.get(section)
        if values is None:
            problems.append(f"{section}: section missing")
            continue
        if not isinstance(values, dict):
            problems.append(f"{section}: expected a map of keys, got {values!r}")
            continue
        for key in values:
            if key not in keys:
                problems.append(f"{section}.{key}: unknown key")
        for key, spec in keys.items():
            path = f"{section}.{key}"
            if key not in values:
                problems.append(f"{path}: key missing")
                continue
            v = values[key]
            if v is None:
                if spec.level == CONNECT:
                    problems.append(f"{path}: TBD (null), required to connect")
                elif spec.level == MISSION and level == MISSION:
                    problems.append(f"{path}: TBD (null), required for a mission")
                continue
            problems.extend(_check_value(path, spec, v))

    cross_problems, warnings = _cross_checks(raw)
    return problems + cross_problems, warnings


def _deep_merge(base, overlay):
    out = copy.deepcopy(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_yaml(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise ConfigError([f"file not found: {path}"], source=str(path)) from None
    except yaml.YAMLError as e:
        raise ConfigError([f"YAML syntax error: {e}"], source=str(path)) from None
    return {} if data is None else data


def load_config(path=DEFAULT_CONFIG, overlay=None, level=CONNECT):
    """Load config.yaml (plus an optional overlay merged on top), validate it at the
    given level, and return a Config. Raises ConfigError listing every problem."""
    raw = _read_yaml(path)
    source = str(path)
    if overlay is not None:
        over = _read_yaml(overlay)
        if not isinstance(over, dict):
            raise ConfigError(["overlay top level must be a map"], source=str(overlay))
        raw = _deep_merge(raw, over) if isinstance(raw, dict) else raw
        source = f"{path} + {overlay}"
    problems, warnings = validate(raw, level)
    if problems:
        raise ConfigError(problems, source=source)
    return Config(raw, derive(raw), warnings, level)


def with_overrides(cfg, overrides):
    """New Config with overrides ({section: {key: value}}) merged on top, validated
    at the same level. For tests and SITL scripts; the mission never calls this."""
    raw = _deep_merge(cfg.raw, overrides)
    problems, warnings = validate(raw, cfg.level)
    if problems:
        raise ConfigError(problems, source="overrides")
    return Config(raw, derive(raw), warnings, cfg.level)


def resolve_path(p):
    """Repo-relative paths in config (logging.dir, calibration_file) -> absolute."""
    p = Path(p).expanduser()
    return p if p.is_absolute() else REPO_ROOT / p
