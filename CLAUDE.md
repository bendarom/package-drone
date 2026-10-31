# Autonomous Pickup Drone


Companion-computer code (Raspberry Pi 5) for a quadcopter that flies from my balcony
to a box, picks it up with a magnet, and flies back. ArduPilot does stabilization and
navigation; this code does mission logic and vision, and commands the FC over MAVLink.
Leave arducam.py unchanged. It's my working test script: it captures frames with
picamera2 and detects AprilTags. Use it as the reference for camera setup and tag
detection.


## Workflow (important)
- Claude Code runs on my computer, NOT on the Pi. You edit this repo, I push to
  GitHub, and the Pi pulls it. You cannot reach the FC, camera, or lidar.
- You CAN run ArduPilot SITL on my computer (see Testing). Run the relevant SITL and
  unit tests yourself before telling me a task is done.
- Work on one phase at a time (see Build order). Show me your plan and any
  assumptions before writing code.
- After any change, tell me what you ran, what passed, and what can only be tested
  on the Pi or in flight.
- On the Pi, the repo lives at ~/drone.


## Hardware (as it affects code)
- Airframe: 4-arm quad, 650 mm frame, 14" props, one 6S battery. All-up weight
  ~2–2.5 kg including the box (box ≈ 0.9 kg / 2 lb).
- FC: Skystars H743 running ArduCopter V4.7.1. On the Pi it's connected via
  /dev/ttyAMA0 at 921600, MAVLink 2. The connection string comes from config.yaml
  so the same code can connect to SITL instead.
- Layout (measure offsets, put them in config.yaml, body frame, meters):
  - Magnet: under the center of the frame.
  - Camera and lidar: at the tail, both facing straight down.
  - The box is thin and hangs under the magnet; it doesn't block the camera or lidar.
- Rangefinder: TFmini Plus wired to the FC (not the Pi). The Pi reads it via MAVLink
  DISTANCE_SENSOR messages.
  - Readings below 0.1 m are invalid (blind zone). Outdoors in sunlight, treat
    readings above ~6 m as unreliable.
  - It's at the tail, so at the box it measures the ground next to the box, not the
    box top.
  - Height above surface = lidar reading − lidar_mount_height_m (height of the lidar
    lens above the ground with the drone resting on its landing gear; I measure it).
- Camera: Arducam OV5647 (v1) on the Pi CSI port, facing down, image top = drone
  tail. Hard-mounted, no gimbal.
  - Nominal FOV ~54° × 41° in full-FOV modes. Use 1296×972. Don't use 1920×1080:
    on this sensor it's a center crop with a smaller FOV.
  - Use a short, fixed exposure to limit motion blur (see arducam.py for settings
    that work).
  - Calibration file: TBD (not done yet), will be calibration/camera.yaml. Until it
    exists, convert pixels to angles using the nominal FOV.
- GPS/compass: BN-880 on the FC. Expect ~2–3 m GPS error; GPS only gets us to the
  area, the AprilTag does final alignment. The magnet doesn't disturb the compass
  (checked: no EKF errors).
- Payload: permanent neodymium magnet under the frame center. No release mechanism,
  and no contact or attachment sensor (see Pickup detection). I remove the box by
  hand after landing on the balcony.
- Pilot override: RadioMaster Pocket via ELRS. Manual RC takeover must always work.
  During autonomous flight I keep the throttle stick centered, so a switch to LOITER
  holds altitude.
- Telemetry radio (915 MHz) to a ground station on a separate FC port. STATUSTEXT
  messages from the Pi show up there.


## AprilTags
- Family tag36h11. Box tag ID 1, balcony tag ID 2 (in config.yaml). Tag size ~7mmx7mm
  (in config.yaml).
- Library: use the same detection library arducam.py uses.
- Tags sit on the ground NEXT TO the box and next to the balcony landing spot, not
  on the box. Each tag is placed so that when the drone is in its target pose
  (magnet over the box center, or drone over the landing spot), the tag is directly
  under the camera and appears upright in the image (tag top edge toward image top).
  So the targets are: tag centered in the image, tag rotation 0. This works at any
  height without calibration.
- The tag must span at least ~30 px at search height and fit fully in the frame at
  commit height. Ground footprint is about $1.0\,h$ wide by $0.75\,h$ tall at
  height $h$. Check this from config at startup and warn if violated.


## Mission sequence
0. Preflight (on the balcony, disarmed): parameter check, GPS 3D fix with at least
   min_sats, EKF healthy, battery above min_start_v, rangefinder healthy, camera
   producing frames, config valid. If anything fails, refuse to start and say why.
1. Wait for me to flip the start switch (RC channel and threshold in config.yaml,
   read from RC_CHANNELS). Then switch to GUIDED, arm, and take off. Home = position
   at arming.
2. Climb straight up until the rangefinder shows 1.0 m above the balcony floor
   (timeout → LAND, which is fine on the balcony). Then keep climbing straight up to
   cruise altitude (baro, relative to home). Nothing is overhead at the balcony. No
   horizontal movement until at cruise altitude.
3. Fly in GUIDED to the box GPS coordinate (in config.yaml, values TBD) at cruise
   altitude (in config.yaml, TBD).
4. Descend straight down to search height above the box ground. If tag 1 isn't
   visible, fly a bounded search pattern at search height. Not found within the
   timeout → failed pickup.
5. Yaw until the tag is upright, center it, then descend. Descend only while the
   centering error is within tolerance; otherwise hold height and re-center. Below
   commit height, stop requiring the tag: no horizontal corrections, descend
   straight down slowly until contact.
6. After contact: pause, climb, run the attachment check (log only), then climb
   straight up to cruise altitude and fly home.
7. Over home at cruise altitude, descend straight down to the balcony approach
   altitude (relative to home; clears the railing with margin). Find tag 2. No
   search pattern near the building. Run the same approach as at the box down to
   the hand-off height above the balcony floor, then switch to LAND. ArduPilot
   disarms on touchdown. I remove the box by hand.
- Failed pickup anywhere in steps 4–6 → climb straight up to cruise altitude and
  continue with step 7. No retries.


## Pickup detection (no dedicated sensor)
- Contact = whichever comes first (log which one):
  - The FC reports landed: EXTENDED_SYS_STATE.landed_state == ON_GROUND.
  - Descent stalled: descent commanded, but vertical speed ≈ 0 for at least
    contact_stall_s, and height above surface ≤ contact_height_max_m (or the lidar
    is invalid because it's in its blind zone).
- After contact, wait magnet_settle_s, then climb. If the FC declared landed, it
  spools to ground idle in GUIDED, so resume with MAV_CMD_NAV_TAKEOFF in GUIDED.
  Otherwise, command a climb directly.
- VERIFY in SITL with ArduCopter 4.7.1 before relying on any of this: what GUIDED
  does after the land detector triggers, whether and when it auto-disarms
  (DISARM_DELAY, throttle stick position), and the altitude frame of the takeoff
  command. At the box the vehicle is below home altitude, so altitudes relative
  to home are negative.
- No contact within descent_timeout_s → failed pickup.
- Attachment check (logging only; the mission returns home either way): compare
  mean VFR_HUD.throttle during a steady hover before descending (above 1 m, so
  ground effect doesn't skew it) with a steady hover at pickup_check_height_m after
  the climb. A rise of at least attach_throttle_rise_pct means "attached". Log it and
  send it as STATUSTEXT. I'll tune the threshold from test flights.


## Failsafe behavior
- "Hold" = GUIDED position target at the current position. "Hand to pilot" = switch
  to LOITER, send STATUSTEXT, stop sending commands.
- Mode changed by anyone but this code → stop all commands immediately, never change
  modes again, log it.
- Unexpected disarm → stop, log, never re-arm.
- Box tag not found within search timeout → failed pickup.
- Tag lost for >2 s, or rangefinder invalid, above commit height → hold. Not
  reacquired within reacquire_timeout_s → failed pickup at the box, or hand to
  pilot at the balcony.
- No contact within descent_timeout_s → failed pickup.
- Balcony tag not found within balcony_tag_timeout_s → hold, then hand to pilot.
- Battery below return_v before pickup → failed pickup.
- Overall mission timeout → return home, or hand to pilot if already at the balcony.
- Unhandled exception in this code → hand to pilot, then exit.
- RC loss, low battery, EKF failure → ArduPilot failsafes handle it (RTL goes to a
  rally point in open ground, not the balcony). This code sees the mode change and
  stops.
- If the Pi dies mid-flight, the drone holds position in GUIDED (velocity commands
  stop after GUID_TIMEOUT). I take over; the FC battery failsafe is the backstop.


## MAVLink notes
- The Pi sends HEARTBEAT at 1 Hz as an onboard controller (sysid/compid in
  config.yaml).
- Request the messages you need at fixed rates with MAV_CMD_SET_MESSAGE_INTERVAL
  (e.g. GLOBAL_POSITION_INT, LOCAL_POSITION_NED, ATTITUDE, DISTANCE_SENSOR,
  EXTENDED_SYS_STATE, VFR_HUD, RC_CHANNELS, BATTERY_STATUS, GPS_RAW_INT,
  EKF_STATUS_REPORT).
- Velocity commands: SET_POSITION_TARGET_LOCAL_NED in the body frame, streamed at
  ≥ 5 Hz. The FC stops on its own after GUID_TIMEOUT without updates.
- The camera has no gimbal: correct the tag's image position for roll and pitch
  (from ATTITUDE) before turning it into a horizontal offset.
- The image-axis-to-body-axis mapping must be confirmed by a bench test before the
  first flight.
- Send STATUSTEXT on every state change and every failsafe.
- This code never writes FC parameters. It only reads them.


## Startup parameter check
- PARAMS.md lists every FC parameter the mission depends on, with expected values
  and why. At startup, main.py reads them over MAVLink and refuses to start if any
  don't match.
- Start with at least these (confirm names and values against the 4.7.1 docs; ask
  me for values you can't decide):
  - Rangefinder: RNGFND1_TYPE (TFmini Plus), RNGFND1_ORIENT (down).
  - Height source is baro, never the rangefinder: EK3_SRC1_POSZ, EK3_RNG_USE_HGT
    disabled.
  - Failsafes: FS_THR_ENABLE, BATT_FS_LOW_ACT, BATT_FS_CRT_ACT, battery voltage
    thresholds, FS_EKF_ACTION.
  - Fence: FENCE_ENABLE, type, radius, max altitude.
  - RTL destination: RALLY_INCL_HOME = 0, with at least one rally point in open
    ground (RALLY_TOTAL ≥ 1).
  - GUID_TIMEOUT, DISARM_DELAY.


## Logging
- Flight-data logging already exists on the Pi: it starts automatically at boot and
  logs MAVLink data from the FC. Don't duplicate it.
- Only one process can open /dev/ttyAMA0. Since the logger starts at boot, it likely
  holds the port before main.py runs. Before writing the connection code, ask me
  how the logger is set up (service name, program, how it opens the port). The
  likely fix is mavlink-router owning /dev/ttyAMA0 and giving the logger and main.py
  each their own UDP endpoint. Put any setup steps in SETUP.md.
- This code still logs every command it sends, every state transition and decision,
  vision results, and key telemetry values to logs/ with timestamps.
- logs/ is in .gitignore; never commit logs.


## Software stack
- Python 3.11, venv at ~/drone-venv (outside the repo, created with system site
  packages).
- Run on the Pi inside tmux, so a dropped Wi-Fi/SSH connection doesn't kill the
  mission:
  `tmux new -s drone`, then
  `cd ~/drone && git pull && source ~/drone-venv/bin/activate && python main.py`
- MAVLink: pymavlink. Do NOT use DroneKit (unmaintained, broken on modern Python).
- Camera: picamera2 (libcamera). cv2.VideoCapture does not work with this camera on
  Pi 5. Vision code must also accept saved images/video so it can be tested off the
  Pi.


## Installing on the Pi
- I install everything on the Pi by hand. Whenever your code needs a new package,
  add it to requirements.txt (pip) or SETUP.md (apt), and tell me the exact install
  command to run on the Pi.
- Prefer apt for numpy, OpenCV (python3-opencv) and picamera2 (python3-picamera2).
  picamera2 depends on the system numpy, and pip-installed versions can break it.
- Already installed: pymavlink (pip, in venv), picamera2 (comes with Raspberry Pi
  OS), and whatever arducam.py imports.


## config.yaml
- All tunables live here. Validate the whole file at startup with clear errors.
- At least:
  - Connection: connection string, baud, Pi sysid/compid, run_mode (real | sitl |
    shadow).
  - Start switch: RC channel and PWM threshold.
  - Positions: box_lat, box_lon (TBD); box_ground_alt_rel_home_m (TBD; negative if
    the balcony is above the ground at the box).
  - Altitudes and speeds: cruise_alt_rel_home_m, cruise_speed_m_s,
    takeoff_check_height_m (1.0), search_height_m, commit_height_m,
    balcony_approach_alt_rel_home_m, balcony_handoff_height_m, descent_speed_m_s,
    final_descent_speed_m_s, max_centering_speed_m_s, centering_tolerance_m.
  - Search: pattern radius, spacing, search_timeout_s.
  - Geometry: camera_offset_m and lidar_offset_m (from drone center),
    lidar_mount_height_m.
  - Tags: family, box_tag_id (1), balcony_tag_id (2), tag_size_m (TBD).
  - Camera: resolution, frame rate, exposure.
  - Pickup: contact_stall_s, contact_height_max_m, magnet_settle_s,
    pickup_check_height_m, attach_throttle_rise_pct.
  - Timeouts: tag_lost_hold_s (2), reacquire_timeout_s, descent_timeout_s,
    balcony_tag_timeout_s, mission_timeout_s.
  - Battery and GPS: min_start_v, return_v, min_sats.


## Project layout
- main.py: mission state machine. Each state has an entry action, a timeout, and
  defined exits.
- config.yaml: see above.
- vision/: tag detection. One interface with three sources: live camera, saved
  images/video, and a simulated source for SITL.
- mav/: MAVLink connection, telemetry, commands, parameter check, mode watcher.
- tools/: bench scripts for the Pi. Read-only: they never arm or send movement
  commands.
- tests/: unit tests (pytest), runnable on my computer.
- sitl/: SITL parameter files and launch helpers.
- calibration/: camera calibration file (once it exists).
- PARAMS.md, SITL.md, SETUP.md: docs.
- logs/: written on the Pi (see Logging).


## Testing
- SITL runs on my computer (OS: Windows 10), not on the Pi.
  - Install ArduPilot outside this repo (e.g. ~/ardupilot), check out the tag that
    matches the FC (Copter-4.7.1), build SITL, and write the exact steps in SITL.md.
  - Simulate a downward rangefinder.
  - SITL ground is flat, so the elevated balcony can't be simulated: use
    box_ground_alt_rel_home_m = 0 in SITL, and unit-test the altitude math with a
    negative value.
  - Simulated tag source: compute where each tag would appear in the image from the
    SITL vehicle position and attitude, the camera offset, and known tag positions,
    so the whole mission runs end to end in SITL.
  - Run with wind and GPS noise. Done means the full mission passes several runs in
    a row, and every failsafe above has a test that triggers it.
  - SITL can't simulate the magnet or the box's weight. Give the attachment check a
    test seam (fake throttle data).
- Vision: unit tests on synthetic tag images and on real photos I take with
  arducam.py (tests/data/).
- Bench tests on the Pi are done with props removed, using tools/ scripts:
  - Telemetry readout: mode, lidar, battery, GPS, throttle.
  - Live tag detection readout.
  - Axis mapping: I move a tag forward and to the right under the camera; the script
    prints which body direction it thinks the tag moved.
  - Standalone parameter check.
- Shadow mode (run_mode: shadow): I fly manually in LOITER. The code runs vision and
  the state machine on real telemetry and logs what it would command, but sends
  nothing.


## Build order
- Do one phase per session, and stop after each one so I can review and commit.
1. Audit this file: list anything ambiguous or contradictory. No code.
2. SITL setup, mav/ connection layer (after asking me about the logger), telemetry,
   mode watcher, parameter check, command logging, config loading and validation.
3. Flight primitives in SITL: takeoff, vertical climb, goto, body velocity, hold,
   hand to pilot, abort on mode change.
4. Vision on saved images, plus the simulated tag source.
5. Tag approach controller (yaw, centering, staircase descent) in SITL.
6. Contact detection and pickup sequence in SITL (verify the GUIDED landing
   behavior above).
7. Full state machine plus failure-injection tests in SITL.
8. Pi bench tools and shadow mode.


## Hard rules
- Never use LAND mode or MAV_CMD_NAV_LAND at the box: they disarm on touchdown. LAND
  is used only for the final touchdown on the balcony.
- The rangefinder is used only for (a) the initial climb on the balcony and (b) tag
  approaches (box and balcony) from search/approach height down, where horizontal
  motion is limited to centering at max_centering_speed_m_s or less. Never use it
  during cruise or transit, and never set it as the EKF height source.
- Near the balcony, altitude changes are vertical only: climb to cruise altitude
  before moving horizontally, and descend only once over home.
- If the flight mode changes and this code didn't change it, stop sending all
  commands immediately and never switch modes again.
- Never re-arm after an unexpected disarm.
- Every loop that commands motion must have a timeout and a defined failsafe (see
  Failsafe behavior).
- Never write code that blocks or disables RC override or ArduPilot failsafes. Never
  write FC parameters.
- Log every command sent and every key telemetry value to logs/ with timestamps.
- Don't arm or send movement commands in any test script unless I explicitly ask.