# Testing

SITL, unit, bench, and shadow-mode testing. Mission behavior and failsafes are in
docs/MISSION.md; hard rules are in CLAUDE.md. SITL tests may arm and fly; nothing
arms or sends movement commands on real hardware unless I explicitly ask.


## SITL
- SITL runs on my computer (Windows 10) in WSL2 with Ubuntu, never Cygwin. Not on
  the Pi.
- Install ArduPilot in the WSL home (~/ardupilot), outside this repo, check out the
  tag that matches the FC (Copter-4.7.1), build SITL, and write the exact steps in
  docs/SITL.md.
- Simulate a downward rangefinder.
- Run with run_mode: sitl, so the parameter check uses params/expected_sitl.yaml.
- SITL ground is flat, so the elevated balcony can't be simulated: use
  box_ground_alt_rel_home_m = 0 in SITL, and unit-test the altitude math with a
  negative value.
- Simulated tag source: compute where each tag would appear in the image from the
  SITL vehicle position and attitude, the camera offset, and known tag positions,
  so the whole mission runs end to end in SITL.
- Wind: steady 5 m/s with turbulence, plus one run at 8 m/s. Keep SITL's default
  GPS noise.
- Done means 5 consecutive full-mission passes, and every failsafe in
  docs/MISSION.md has a test that triggers it.
- GUIDED landing verification (see docs/MISSION.md, Pickup detection): measure how
  long after touchdown GUIDED would auto-disarm, and report the margin between
  contact detection starting the climb and that disarm.
- SITL can't simulate the magnet or the box's weight. Give the attachment check a
  test seam (fake throttle data).


## Vision
- Unit tests on synthetic tag images and on real photos I take with arducam.py
  (tests/data/).


## Bench tests (on the Pi, props removed, using tools/ scripts)
tools/ scripts never arm or send movement commands.
- Telemetry readout: mode, lidar, battery, GPS, throttle.
- Live tag detection readout.
- Camera mode: print the sensor mode picamera2 actually picked (must be the full-FOV
  1296×972 mode), plus output size and exposure settings.
- Axis mapping: I move a tag forward and to the right under the camera; the script
  prints which body direction it thinks the tag moved.
- Standalone parameter check.


## Shadow mode (run_mode: shadow)
- I fly manually in LOITER. The code runs vision and the state machine on real
  telemetry and logs what it would command.
- Parameter check uses params/expected_real.yaml.
- The mode watcher only logs mode changes; it never aborts, since the code never
  takes control.
- Allowed to send: HEARTBEAT, SET_MESSAGE_INTERVAL, parameter reads, STATUSTEXT.
  Never: arming, mode changes, takeoff, or any position/velocity command.
