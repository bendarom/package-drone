# Autonomous Pickup Drone

Companion-computer code (Raspberry Pi 5) for a quadcopter that flies from my balcony
to a box, picks it up with a magnet, and flies back. ArduPilot does stabilization and
navigation; this code does mission logic and vision, and commands the FC over MAVLink.
There are already two files, arducam.py, lidar.py, and connectiontest.py. leave them unchanged.

## Workflow (important)
- Claude Code does NOT run on the Pi. You edit this repo, I push to GitHub, and the
  Pi pulls it. You cannot reach the FC, camera, or lidar.
- After any change, tell me what you tested and what can only be tested on the Pi.
- On the Pi, the repo lives at ~/drone.

## Hardware (as it affects code)
- FC: Skystars H743 running ArduCopter V4.7.1. On the Pi it's connected via
  /dev/ttyAMA0 at 921600, MAVLink 2. The connection string comes from config.yaml
  so the same code can connect to SITL instead.
- Rangefinder: TFmini Plus wired to the FC (not the Pi). The Pi reads it via MAVLink
  DISTANCE_SENSOR messages. Faces straight down.
- Camera: Arducam OV5647 on the Pi CSI port, mounted facing down,
  image top = drone tail.
  Calibration file: TBD (not done yet), will be calibration/camera.yaml in this repo.
  Centering works in pixels for now.
- GPS/compass: BN-880 on the FC. Expect ~2–3 m GPS error; GPS only gets us to the
  area, the AprilTag does final alignment.
- Payload: permanent neodymium magnet under the frame. No release mechanism.
  I remove the box by hand after landing on the balcony.
- Pilot override: RadioMaster Pocket via ELRS. Manual RC takeover must always work.

## Mission sequence
1. Arm on balcony. Climb until the rangefinder reads 1.0 m, then hold that altitude
   relative to home (baro) BEFORE any horizontal movement.
2. Fly in GUIDED to the box GPS coordinate (in config.yaml, values TBD) at cruise
   altitude (in config.yaml, TBD).
3. Detect box tag (ID 1, in config.yaml), center over it using camera.
4. Descend slowly in GUIDED using rangefinder until contact; magnet engages.
5. Climb to cruise altitude, fly back to home (position recorded at arming;
   no separate balcony coordinate needed).
6. Detect balcony tag (ID 2, in config.yaml), center, descend and land on the
   balcony with the box still attached. I remove the box by hand after disarm.

## Software stack
- Python 3.11, venv at ~/drone-venv (outside the repo, created with
  system site packages).
- Run on the Pi:
  `cd ~/drone && git pull && source ~/drone-venv/bin/activate && python main.py`
- MAVLink: pymavlink. Do NOT use DroneKit (unmaintained, broken on modern Python).
- Camera: picamera2 (libcamera). cv2.VideoCapture does not work with this camera on Pi 5.
  Vision code must also accept saved images/video so it can be tested off the Pi.
- AprilTags: library TBD, family tag36h11, tag size TBD (in config.yaml).

## Installing on the Pi
- I install everything on the Pi by hand. Whenever your code needs a new package,
  add it to requirements.txt (pip) or SETUP.md (apt), and tell me the exact
  install command to run on the Pi.
- Prefer apt for numpy, OpenCV (python3-opencv) and picamera2 (python3-picamera2).
  picamera2 depends on the system numpy, and pip-installed versions can break it.
- Already installed: pymavlink (pip, in venv), picamera2 (comes with Raspberry Pi OS).

## Project layout
- main.py: mission state machine
- config.yaml: coordinates, altitudes, tag IDs, connection string, timeouts
- vision/: tag detection
- mav/: MAVLink connection and commands
- calibration/: camera calibration file (once it exists)
- logs/: flight logs, written on the Pi. FC onboard logging is broken, so this is
  the only log. In .gitignore; never commit logs.

## Testing
- Test all mission logic in ArduPilot SITL first (runs on a computer, not the Pi):
  TBD (not set up yet).
- Bench tests with real hardware are done with props removed.

## Hard rules
- Never use LAND mode or MAV_CMD_NAV_LAND at the box: they disarm on touchdown.
- The rangefinder is used only for (a) the initial climb on the balcony and (b) the
  final descent onto the box. Never use it for altitude while moving horizontally,
  and never set it as the EKF height source.
- Every loop that commands motion must have a timeout and a defined failsafe
  (e.g. tag lost for >2 s → hold position, then RTL).
- Never write code that blocks or disables RC override or ArduPilot failsafes.
- Log every command sent and every key telemetry value to logs/ with timestamps.
- Don't arm or send movement commands in any test script unless I explicitly ask.