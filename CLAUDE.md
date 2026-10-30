# Autonomous Pickup Drone

Companion-computer code (Raspberry Pi 5) for a quadcopter that flies from my balcony
to a box, picks it up with a magnet, and flies back. ArduPilot does stabilization and
navigation; this code does mission logic and vision, and commands the FC over MAVLink.

## Hardware (as it affects code)
- FC: Skystars H743 running ArduCopter V4.7.1, connected to Pi via
  /dev/ttyAMA0 at 921600. MAVLink 2.
- Rangefinder: TFmini Plus wired to the FC (not the Pi). The Pi reads it via MAVLink
  DISTANCE_SENSOR messages. Faces straight down.
- Camera: Arducam OV5647 on the Pi CSI port, mounted facing down,
  image top = drone tail.
  Calibration file: TBD.
- GPS/compass: BN-880 on the FC. Expect ~2–3 m GPS error; GPS only gets us to the
  area, the AprilTag does final alignment.
- Payload: permanent neodymium magnet under the frame. No release mechanism - I remove the box by hand after landing on the balcony.
- Pilot override: RadioMaster Pocket via ELRS. Manual RC takeover must always work.

## Mission sequence
1. Arm on balcony. Climb until the rangefinder reads 1.0 m, then hold that altitude relative to home (baro) BEFORE any horizontal movement.
2. Fly in GUIDED to box GPS coordinate [where stored] at [Y] m.
3. Detect box tag (ID [n]), center over it using camera.
4. Descend slowly in GUIDED using rangefinder until contact; magnet engages.
5. Climb to [Y] m, fly to balcony GPS coordinate.
6. Detect balcony tag (ID [m]), center, descend and land on the balcony with the box still attached. I remove the box by hand after disarm. There is no release mechanism.

## Software stack
- Python [3.11], venv at [path]. Run: `[command]`
- MAVLink: pymavlink [or MAVSDK]. Do NOT use DroneKit (unmaintained, broken on
  modern Python).
- Camera: picamera2 (libcamera). cv2.VideoCapture does not work with this camera on Pi 5.
- AprilTags: [library], family tag36h11 [confirm], tag size [N] mm (needed for pose).

## Project layout
- [main.py — mission state machine]
- [vision/ — tag detection and pose]
- [mav/ — MAVLink connection and commands]
- [logs/ — all flight logs (FC onboard logging is broken; Pi is the only log)]

## Testing
- Test all mission logic in ArduPilot SITL first: `[command]`
- Bench tests with real hardware are done with props removed.

## Hard rules
- Never use LAND mode or MAV_CMD_NAV_LAND at the box: they disarm on touchdown.
- The rangefinder is used only for (a) the initial climb on the balcony and (b) the final descent onto the box. Never use it for altitude while moving horizontally, and never set it as the EKF height source.
- Every loop that commands motion must have a timeout and a defined failsafe
  (e.g. tag lost for >[t] s → hold position, then RTL).
- Never write code that blocks or disables RC override or ArduPilot failsafes.
- Log every command sent and every key telemetry value to logs/ with timestamps.
- Don't arm or send movement commands in any test script unless I explicitly ask.