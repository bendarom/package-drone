# Autonomous Pickup Drone

Companion-computer code (Raspberry Pi 5) for a quadcopter that flies from my balcony
to a box, picks it up with a magnet, and flies back. ArduPilot does stabilization and
navigation; this code does mission logic and vision, and commands the FC over MAVLink.
arducam.py is my working demo (picamera2 capture + AprilTag detection). Keep it
unchanged. Don't copy its resolution or exposure; mission code also filters by tag ID.

## Read these first
- docs/MISSION.md: mission sequence, tags, pickup detection, failsafes, MAVLink rules.
  Read it before working on main.py, mav/, vision/, or anything that commands flight.
- docs/TESTING.md: SITL, unit, bench, and shadow-mode testing. Read it before writing
  or running tests, touching sitl/ or tools/, or telling me a task is done.
- docs/PARAMS.md, docs/SITL.md, docs/SETUP.md: read the matching one before touching
  params/, SITL setup, or Pi setup.

## Open items
- OpenCV on the Pi (apt python3-opencv 4.6 vs pip >=4.7, which arducam.py's
  ArucoDetector needs) is unresolved. Before starting any vision work, remind me to
  check what's installed on the Pi. Until then, don't change the OpenCV lines in
  requirements.txt or the OpenCV install docs.

## Workflow (important)
- Claude Code runs on my computer (Windows 10), NOT on the Pi. You edit this repo, I
  push to GitHub, and the Pi pulls it. You cannot reach the FC, camera, or lidar.
- You CAN run ArduPilot SITL (in WSL2 Ubuntu) and unit tests on my computer. Run the
  relevant ones yourself before telling me a task is done.
- One task at a time; stop after each so I can review and commit. Show me your plan
  and any assumptions before writing code.
- After any change, tell me what you ran, what passed, and what can only be tested
  on the Pi or in flight.

## Hardware (as it affects code)
- Quad, 650 mm frame, 14" props, one 6S battery. ~2–2.5 kg all-up incl. box (~0.9 kg).
- FC: Skystars H743, ArduCopter V4.7.1. On the Pi: /dev/ttyAMA0, 921600, MAVLink 2.
  The connection string comes from config.yaml so the same code can connect to SITL.
- Magnet (permanent neodymium) under the frame center. No release mechanism, no
  attachment sensor; I remove the box by hand after landing. The magnet doesn't
  disturb the compass. Contact geometry is in docs/MISSION.md.
- Camera and lidar are at the tail, both facing straight down. I measure their
  offsets and put them in config.yaml (body frame, meters).
- Rangefinder: TFmini Plus wired to the FC; the Pi reads DISTANCE_SENSOR. Invalid
  below 0.1 m; unreliable above ~6 m in sunlight. At the box it measures the ground
  next to the box. Height above surface = reading − lidar_mount_height_m (lens
  height with the drone resting on its landing gear on flat ground).
- Camera: Arducam OV5647 (v1) on CSI, image top = drone tail, no gimbal. Nominal FOV
  ~54° × 41°. Explicitly select the full-FOV 1296×972 sensor mode and use 1296×972
  output (1920×1080 is a center crop). Exposure is configurable: auto by default,
  optionally capped or fixed. Until calibration/camera.yaml exists, use nominal FOV.
- GPS/compass: BN-880 on the FC, ~2–3 m error. GPS gets us to the area; AprilTags do
  final alignment.
- Pilot override: RadioMaster Pocket via ELRS; manual takeover must always work. I
  keep the throttle stick centered in autonomous flight, so LOITER holds altitude.
- Telemetry radio (915 MHz) to a ground station on another FC port; STATUSTEXT
  messages from the Pi show up there.

## Software stack
- Python 3.11. On the Pi: repo at ~/drone, venv at ~/drone-venv (outside the repo,
  system site packages). Run inside tmux so a dropped SSH session doesn't kill it:
  `tmux new -s drone`, then
  `cd ~/drone && git pull && source ~/drone-venv/bin/activate && python main.py`
- MAVLink: pymavlink. Do NOT use DroneKit (unmaintained, broken on modern Python).
- Camera: picamera2 (libcamera); cv2.VideoCapture doesn't work with it on Pi 5.
  Vision code must also accept saved images/video so it can be tested off the Pi.
- I install everything on the Pi by hand. When code needs a new package, add it to
  requirements.txt (pip) or docs/SETUP.md (apt) and give me the exact command. Prefer
  apt for numpy and picamera2 (python3-picamera2); pip versions can break
  picamera2's system numpy. Already installed: pymavlink (pip, venv), picamera2.
- A flight-data logger already starts at boot on the Pi and logs FC MAVLink; don't
  duplicate it. It likely holds /dev/ttyAMA0 (one process per port). Ask me how it's
  set up before writing connection code. Likely fix: mavlink-router owns the port and
  gives the logger and main.py their own UDP endpoints; steps go in docs/SETUP.md.

## Project layout
- main.py: mission state machine. Each state has an entry action, a timeout, and
  defined exits.
- config.yaml: all tunables. Validate the whole file at startup with clear errors.
- mav/: MAVLink connection, telemetry, commands, parameter check, mode watcher.
- vision/: tag detection. One interface, three sources: live camera, saved
  images/video, and a simulated source for SITL.
- params/: expected_real.yaml and expected_sitl.yaml (name, value, tolerance,
  reason). run_mode picks the file; shadow uses real. Explained in docs/PARAMS.md.
- tools/: Pi bench scripts. Read-only: they never arm or send movement commands.
- tests/: pytest unit tests, runnable on my computer (real photos in tests/data/).
- sitl/: SITL parameter files and launch helpers.
- calibration/: camera calibration file (once it exists). logs/: written on the Pi.
- docs/: MISSION.md, TESTING.md, PARAMS.md, SITL.md, SETUP.md.

## Hard rules
- Never use LAND mode or MAV_CMD_NAV_LAND at the box: they disarm on touchdown. LAND
  is allowed only on the balcony: for the final touchdown, and to abort the initial
  climb (still over the balcony, before any horizontal movement).
- The rangefinder is used only for (a) the initial climb on the balcony and (b) tag
  approaches (box and balcony) after the tag is acquired, with horizontal motion
  limited to centering at max_centering_speed_m_s or less. Never use it during
  cruise, transit, or search, and never set it as the EKF height source.
- Near the balcony, no transit movement below cruise altitude: climb straight up to
  cruise before moving horizontally, and descend only once over home. Tag centering
  during the balcony approach (≤ max_centering_speed_m_s) is allowed.
- If the flight mode changes and this code didn't change it, stop sending all
  commands immediately and never switch modes again (shadow mode: log only).
- This code never commands RTL. RTL only comes from ArduPilot's own failsafes.
- Never re-arm after an unexpected disarm.
- Every loop that commands motion must have a timeout and a defined failsafe (see
  docs/MISSION.md).
- Never write code that blocks or disables RC override or ArduPilot failsafes. Never
  write FC parameters; only read them.
- Log every command sent, state transition, decision, vision result, and key
  telemetry value to logs/ with timestamps. logs/ is gitignored; never commit logs.
- On real hardware, nothing arms or sends movement commands except main.py in real
  mode, unless I explicitly ask. tools/ scripts never do. SITL tests may arm and fly.
