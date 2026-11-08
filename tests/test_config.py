import pytest
import yaml

from config import (CONNECT, MISSION, ConfigError, derive, load_config, tag_pixels, validate,
                    with_overrides)

from conftest import REPO_ROOT


def test_repo_config_valid_at_connect_level():
    cfg = load_config()
    assert cfg.connection.sysid == 1
    assert cfg.run_mode == "real"


def test_repo_config_not_ready_for_mission():
    with pytest.raises(ConfigError) as e:
        load_config(level=MISSION)
    msg = str(e.value)
    assert "altitudes.cruise_alt_rel_home_m: TBD (null), required for a mission" in msg
    assert "geometry.box_thickness_m: TBD (null)" in msg


def test_filled_config_valid_for_mission(mission_raw):
    problems, warnings = validate(mission_raw, MISSION)
    assert problems == []
    assert warnings == []


def test_sitl_overlay():
    cfg = load_config(overlay=REPO_ROOT / "sitl" / "config.sitl.yaml")
    assert cfg.connection.connection_string == "tcp:127.0.0.1:5762"
    assert cfg.run_mode == "sitl"
    assert cfg.positions.box_ground_alt_rel_home_m == 0
    assert cfg.connection.baud == 921600   # untouched keys kept from config.yaml


def test_all_problems_reported_at_once(raw):
    raw["connection"]["sysid"] = "one"
    raw["speeds"]["warp_factor"] = 9
    raw["altitudes"]["commit_height_m"] = -1
    raw["bogus"] = {}
    problems, _ = validate(raw, CONNECT)
    assert "connection.sysid: expected an integer, got 'one'" in problems
    assert "speeds.warp_factor: unknown key" in problems
    assert "altitudes.commit_height_m: must be > 0, got -1" in problems
    assert "bogus: unknown section" in problems


def test_connect_keys_never_null(raw):
    raw["connection"]["connection_string"] = None
    problems, _ = validate(raw, CONNECT)
    assert "connection.connection_string: TBD (null), required to connect" in problems


def test_missing_key_and_section(raw):
    del raw["connection"]["baud"]
    del raw["logging"]
    problems, _ = validate(raw, CONNECT)
    assert "connection.baud: key missing" in problems
    assert "logging: section missing" in problems


def test_bool_is_not_a_number(raw):
    raw["altitudes"]["search_height_m"] = True
    problems, _ = validate(raw, CONNECT)
    assert any(p.startswith("altitudes.search_height_m: expected a number") for p in problems)


def test_bad_run_mode(raw):
    raw["connection"]["run_mode"] = "fly"
    problems, _ = validate(raw, CONNECT)
    assert any(p.startswith("connection.run_mode: must be one of real, sitl, shadow") for p in problems)


def test_bad_rates(raw):
    raw["telemetry"]["rates_hz"]["ATTITUDE"] = 0
    raw["telemetry"]["rates_hz"]["attitude"] = 5
    problems, _ = validate(raw, CONNECT)
    assert "telemetry.rates_hz.ATTITUDE: rate must be a number > 0 Hz, got 0" in problems
    assert any(p.startswith("telemetry.rates_hz.attitude: message names are upper case") for p in problems)


def test_magnet_cannot_reach_box(mission_raw):
    mission_raw["geometry"]["magnet_clearance_m"] = 0.2
    problems, _ = validate(mission_raw, MISSION)
    assert any("the magnet could never reach the box" in p for p in problems)


def test_height_order(mission_raw):
    mission_raw["altitudes"]["pickup_check_height_m"] = 0.4
    problems, _ = validate(mission_raw, MISSION)
    assert any("commit_height_m < pickup_check_height_m < search_height_m" in p for p in problems)


def test_sitl_requires_flat_box_ground(mission_raw):
    mission_raw["connection"]["run_mode"] = "sitl"
    problems, _ = validate(mission_raw, MISSION)   # mission_raw has -9.0
    assert "positions.box_ground_alt_rel_home_m must be 0 in SITL (flat ground), got -9.0" in problems


def test_velocity_rate_minimum(mission_raw):
    mission_raw["commands"]["velocity_rate_hz"] = 4
    problems, _ = validate(mission_raw, MISSION)
    assert "commands.velocity_rate_hz must be >= 5 Hz, got 4" in problems


def test_offsets_must_be_vec3(mission_raw):
    mission_raw["geometry"]["camera_offset_m"] = [0.1, 0.2]
    problems, _ = validate(mission_raw, MISSION)
    assert any(p.startswith("geometry.camera_offset_m: expected a list of 3 numbers") for p in problems)


def test_return_v_below_start_v(mission_raw):
    mission_raw["battery_gps"]["return_v"] = 25.0
    problems, _ = validate(mission_raw, MISSION)
    assert any(p.startswith("battery_gps: return_v") for p in problems)


def test_exposure_time_required_when_capped(mission_raw):
    mission_raw["camera"]["exposure_mode"] = "cap"
    problems, _ = validate(mission_raw, MISSION)
    assert "camera.exposure_time_us is required when exposure_mode is cap" in problems


def test_derived_contact_height(mission_raw):
    d = derive(mission_raw)
    assert d["contact_height_max_m"] == pytest.approx((0.15 - 0.05) + 0.05)


def test_negative_box_ground_altitude_math(mission_raw):
    # Balcony 9 m above the box ground: searching 5 m above the box is 4 m below home.
    d = derive(mission_raw)
    assert d["search_alt_rel_home_m"] == pytest.approx(-4.0)
    problems, _ = validate(mission_raw, MISSION)
    assert problems == []


def test_search_altitude_must_be_below_cruise(mission_raw):
    mission_raw["positions"]["box_ground_alt_rel_home_m"] = 4.0   # search alt 9 m > cruise 8 m
    problems, _ = validate(mission_raw, MISSION)
    assert any("must be below cruise_alt_rel_home_m" in p for p in problems)


def test_tag_pixel_size_matches_mission_doc():
    # MISSION.md: at 5 m a 0.16 m tag is ~41 px wide.
    px_w, _ = tag_pixels(0.16, 5.0, [1296, 972], [54.0, 41.0])
    assert px_w == pytest.approx(41, abs=1)


def test_tag_too_small_warns(mission_raw):
    mission_raw["tags"]["tag_size_m"] = 0.08
    problems, warnings = validate(mission_raw, MISSION)
    assert problems == []
    assert any("spans only" in w for w in warnings)


def test_tag_too_big_at_commit_warns(mission_raw):
    mission_raw["tags"]["tag_size_m"] = 0.5
    _, warnings = validate(mission_raw, MISSION)
    assert any("doesn't fit in the frame" in w for w in warnings)


def test_config_is_read_only():
    cfg = load_config()
    with pytest.raises(AttributeError):
        cfg.connection.sysid = 2
    with pytest.raises(AttributeError):
        cfg.connection.no_such_key


def test_with_overrides_validates():
    cfg = load_config()
    shadow = with_overrides(cfg, {"connection": {"run_mode": "shadow"}})
    assert shadow.run_mode == "shadow" and cfg.run_mode == "real"
    with pytest.raises(ConfigError):
        with_overrides(cfg, {"connection": {"run_mode": "nope"}})


def test_yaml_syntax_error(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("connection: [unclosed\n")
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "YAML syntax error" in str(e.value)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_config(tmp_path / "nope.yaml")
    assert "file not found" in str(e.value)


def test_overlay_unknown_key_rejected(tmp_path):
    p = tmp_path / "overlay.yaml"
    p.write_text(yaml.safe_dump({"connection": {"conection_string": "tcp:1.2.3.4:5"}}))
    with pytest.raises(ConfigError) as e:
        load_config(overlay=p)
    assert "connection.conection_string: unknown key" in str(e.value)
