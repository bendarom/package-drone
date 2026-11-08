# Parameter check

At startup the mission code reads FC parameters and compares them with
`params/expected_<real|sitl>.yaml`. Hard rules are in CLAUDE.md.

- **Read-only.** Each parameter is read with PARAM_REQUEST_READ. The code never sends
  PARAM_SET. The send gate in `mav/connection.py` blocks PARAM_SET, PARAM_EXT_SET,
  MAV_CMD_DO_SET_PARAMETER and MAV_CMD_PREFLIGHT_STORAGE in every run mode. If a value
  is wrong, change it yourself in Mission Planner.
- **Which file:** `run_mode: sitl` uses `expected_sitl.yaml`. `real` and `shadow` use
  `expected_real.yaml`.
- **Passes only if every entry is PASS.** Any FAIL, MISSING or TBD fails the check, and
  the mission refuses to start (main.py, later).
- Standalone run (bench test, also SITL):
  `python tools/check_params.py` (add `--overlay sitl/config.sitl.yaml` for SITL, or
  `--expected real|sitl` to pick the file by hand). Exit code 0 only on PASS.


## File format

```yaml
params:
  - name: RNGFND1_MIN      # exact ArduPilot name (<= 16 chars, upper case)
    value: 0.1             # number, or null = TBD
    tolerance: 0.001       # optional, default 0
    op: eq                 # optional: eq (default, |actual - value| <= tolerance),
                           #   ge, le, bits_set (all bits of value set in actual)
    reason: why it matters # required; printed when the entry fails
```

Values come back as float32, so a small epsilon is always allowed (0.1 matches
0.100000001). Unknown keys, duplicate names, a missing reason or a bad op make the
file invalid.

Results:

| Status  | Meaning |
|---------|---------|
| PASS    | Matches |
| FAIL    | Doesn't match. The report shows the actual value, the expected value and the reason |
| MISSING | No PARAM_VALUE reply: the name doesn't exist in this firmware, or the link failed |
| TBD     | Expected value is still null. The FC's current value is shown so you can decide |


## ArduPilot 4.7 renames

Checked against a Copter-4.7.1 SITL dump:
- `SYSID_THISMAV` is now `MAV_SYSID`.
- `ARMING_CHECK` is now `ARMING_SKIPCHK`, with inverted meaning: a bitmask of checks
  to skip, so 0 means all checks are on.


## What is checked and why

Both files:
- `MAV_SYSID` = 1: the mission code talks to sysid 1 (config `connection.sysid`).
- `RNGFND1_ORIENT` = 25 (down), `RNGFND1_MIN` = 0.1, `RNGFND1_MAX` = 12: TFmini Plus
  range. Must match config `rangefinder.min_valid_m`.
- `EK3_SRC1_POSZ` = 1 (baro) and `EK3_RNG_USE_HGT` = -1: the rangefinder is never the
  EKF height source (hard rule).

SITL only (`expected_sitl.yaml`, every value matches the SITL defaults plus
`sitl/rangefinder.parm`):
- `RNGFND1_TYPE` = 100 (simulated).
- `SERIAL1_PROTOCOL` = 2: tcp 5762 is the mission-code link.
- `GUID_TIMEOUT` 3, `DISARM_DELAY` 10, `FS_THR_ENABLE` 1, `FS_EKF_ACTION` 1,
  `ARMING_SKIPCHK` 0: catch a SITL eeprom that has drifted from the defaults.

Real only (`expected_real.yaml`):
- `RNGFND1_TYPE` = 20: Benewake serial driver, because the TFmini Plus is on a UART.
- `RALLY_TOTAL` >= 1 and `RALLY_INCL_HOME` = 0: ArduPilot RTL must go to a rally point
  in open ground, never home (the balcony). MISSION.md failsafes.
- TBD until you send the FC parameter dump:
  - `GUID_TIMEOUT`: MISSION.md relies on it to stop the drone if the Pi dies.
  - `DISARM_DELAY`: contact detection must start the climb well before any
    auto-disarm. It will be measured in SITL later.
  - `FS_THR_ENABLE`, `FS_EKF_ACTION`, `FS_GCS_ENABLE`, `BATT_FS_LOW_ACT`,
    `BATT_FS_CRT_ACT`, `BATT_LOW_VOLT` (must be below config `battery_gps.return_v`),
    `ARMING_SKIPCHK`.
  - Note: the GCS failsafe watches heartbeats from `MAV_GCS_SYSID` (255 by default).
    The Pi (sysid 1, compid 191) doesn't count as a GCS.


## Open items

1. **FC parameter dump.** In Mission Planner: Config → Full Parameter List → Save, as
   `params/fc_current.param`. I'll propose values for every TBD entry from it, flag
   anything that looks unsafe, and fill them in once you confirm.
2. **FC serial ports.** Which SERIALn the Pi is on, and which SERIALm the TFmini Plus
   is on. Then add these to `expected_real.yaml` (a commented template is at the end
   of that file):
   - Pi port: `SERIALn_PROTOCOL` = 2 and `SERIALn_BAUD` = 921.
   - Lidar port: `SERIALm_PROTOCOL` = 9 and `SERIALm_BAUD` = 115.
   The dump answers this too: look for the SERIALx_PROTOCOL = 9 entry.
