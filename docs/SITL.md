# SITL

ArduPilot SITL for testing mission code on my computer (Windows 10). Testing rules are
in docs/TESTING.md. SITL runs in WSL2 Ubuntu 24.04, never Cygwin. ArduPilot lives in the
WSL home (`~/ardupilot`), outside this repo, at tag `Copter-4.7.1` to match the FC.

Paths used below:
- ArduPilot checkout: `~/ardupilot` (WSL)
- SITL run dir (eeprom, logs, params): `~/sitl-copter` (WSL), outside the repo
- This repo from WSL: `/mnt/c/Users/benbe/OneDrive/Documents/Drone`


## Install (once)

In Windows PowerShell:

```
wsl --install -d Ubuntu-24.04
```

Create the Linux user when asked, then in the Ubuntu shell:

```
sudo apt-get update && sudo apt-get install -y git
git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git ~/ardupilot
cd ~/ardupilot
git checkout Copter-4.7.1
git submodule update --init --recursive
Tools/environment_install/install-prereqs-ubuntu.sh -y
. ~/.profile
./waf configure --board sitl
./waf copter
```

Check the checkout: `git rev-parse HEAD` must print
`dbe792162d06cab66c3475fd5556bf7a120f119e` (`git describe` may show `AP_Periph-4.7.1`,
which tags the same commit).

`install-prereqs-ubuntu.sh` adds `Tools/autotest` (for `sim_vehicle.py`) and the ArduPilot
Python venv to `~/.profile`, so open a new Ubuntu shell (or run `. ~/.profile`) first.


## Start location (balcony)

SITL starts at `SITL_HOME`, given as `lat,lon,alt,heading`:

```
SITL_HOME="-35.363262,149.165237,584,353"   # PLACEHOLDER: ArduPilot's default CMAC field
```

To change it to the balcony, replace the four values:
- `lat`, `lon`: balcony takeoff spot, decimal degrees (south and west are negative).
- `alt`: balcony floor altitude in meters **above sea level** (AMSL), not relative to
  the ground.
- `heading`: direction the drone's nose points at takeoff, degrees, 0 = north,
  90 = east.

Then reset SITL (below) once, so the old home and EKF state don't carry over.

SITL ground is flat at the home altitude, so the balcony's height above the box ground
can't be simulated: use `box_ground_alt_rel_home_m = 0` in SITL (docs/TESTING.md).


## Start

In an Ubuntu shell:

```
SITL_HOME="-35.363262,149.165237,584,353"   # PLACEHOLDER, see above
cd ~/ardupilot
sim_vehicle.py -v ArduCopter -f quad --no-rebuild \
  --custom-location=$SITL_HOME \
  --use-dir ~/sitl-copter \
  --add-param-file=/mnt/c/Users/benbe/OneDrive/Documents/Drone/sitl/rangefinder.parm
```

This opens a MAVProxy prompt in the same terminal. Windows 10 has no WSLg, so don't
use `--console` or `--map`.

Ports:
- MAVProxy uses TCP 5760.
- Mission code or a ground station connects on **`tcp:127.0.0.1:5762`** (SITL's
  SERIAL1). This works from WSL and, through WSL localhost forwarding, from Windows.
  (config.yaml's comment says 5760; that only works when MAVProxy isn't running.)

Simulated downward rangefinder: `sitl/rangefinder.parm` (SITL type 100, facing down,
0.1–12 m). It is loaded on every start. The EKF height source stays at the default
(baro). `RNGFND1_POS_*` and `RNGFND1_GNDCLR` stay at defaults until the lidar offset
and mount height are measured.

GPS noise is SITL's default. Wind isn't configured yet.


## Check GPS fix and rangefinder

At the MAVProxy prompt (allow ~30 s after start):

```
status GPS_RAW_INT
status DISTANCE_SENSOR
```

`fix_type` must be 3 or higher (SITL reports 6 with 10 sats). `DISTANCE_SENSOR` must
show `orientation 25`, `min_distance 10`, `max_distance 1200` (cm). On the ground SITL
reports `current_distance 0`, below `RNGFND1_MIN`, so the reading counts as out of range
until the vehicle climbs. The real TFmini reads its mount height instead.

`Failed to download /SRTM3/...` in the MAVProxy output is the terrain module failing
to fetch elevation tiles. It's harmless: SITL ground is flat anyway.

Without MAVProxy, from another Ubuntu shell:

```
cd ~/ardupilot && python3 -c "
from pymavlink import mavutil
m = mavutil.mavlink_connection('tcp:127.0.0.1:5762'); m.wait_heartbeat()
m.mav.request_data_stream_send(m.target_system, m.target_component, 0, 4, 1)
print(m.recv_match(type='GPS_RAW_INT', condition='GPS_RAW_INT.fix_type>=3', blocking=True, timeout=120))
print(m.recv_match(type='DISTANCE_SENSOR', blocking=True, timeout=30))"
```


## Stop

Type `exit` at the MAVProxy prompt (or press Ctrl-C). If anything is left running:

```
pkill -f '[a]rducopter'; pkill -f '[m]avproxy.py'; pkill -f '[s]im_vehicle.py'
pgrep -fa '[a]rducopter|[m]avproxy|[s]im_vehicle' || echo stopped
```

(The brackets stop `pkill -f` from matching, and killing, the shell or script that
runs it.)


## Reset

Stop SITL, then delete the run dir (eeprom with saved params, logs, and the old home):

```
rm -rf ~/sitl-copter
```

Or wipe eeprom on a single start by adding `-w` to the start command.
