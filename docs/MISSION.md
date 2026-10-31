# Mission

Mission sequence, tags, pickup detection, failsafes, and MAVLink command rules.
Hardware facts and hard rules are in CLAUDE.md. Key names refer to config.yaml.


## Site
- Balcony: nothing overhead. The landing spot is 3 m from the building wall.
- Box: on open ground below the balcony level (box_ground_alt_rel_home_m is
  negative if the balcony is above the ground at the box).


## AprilTags
- Family tag36h11. Box tag ID 1, balcony tag ID 2. Detection library: the same one
  arducam.py uses. Mission code ignores tags with any other ID.
- Size: tag_size_m = edge of the black square (outer edge of the black border,
  excluding the white margin). Currently 0.16 m, printed with a 2 cm white margin
  (20 cm total). I'll replace it with the measured printed size.
- Tags sit on the ground NEXT TO the box and next to the balcony landing spot, not
  on the box. Each tag is placed so that when the drone is in its target pose
  (magnet over the box center, or drone over the landing spot), the tag is directly
  under the camera and appears upright in the image (tag top edge toward image top).
  So the targets are: tag centered in the image, tag rotation 0. This works at any
  height without calibration.
- The tag must span at least ~30 px at search_height_m and fit fully in the frame at
  commit_height_m. Ground footprint at height h is about 1.0·h wide by 0.75·h tall
  (at 5 m a 0.16 m tag is ~41 px). Check this from config at startup and warn if
  violated.
- Acquired = the target tag seen in tag_acquire_frames (3) consecutive frames.


## Contact geometry
- box_thickness_m: box height above the ground.
- magnet_clearance_m: height of the magnet face above the bottom of the landing gear,
  with the drone resting on flat ground.
- The magnet touches the box first, and the drone ends up resting on the box.
- contact_height_max_m = (box_thickness_m − magnet_clearance_m) + 0.05, derived at
  startup (not set in config). Height is lidar height above the ground next to
  the box.
- At startup, refuse to run if magnet_clearance_m > box_thickness_m (the magnet
  could never reach the box).


## Mission sequence
0. Preflight (on the balcony, disarmed). If anything fails, refuse to start and say
   why:
   - Parameter check against params/expected_<real|sitl>.yaml (see docs/PARAMS.md).
   - GPS 3D fix with at least min_sats, EKF healthy, battery above min_start_v.
   - Rangefinder healthy: DISTANCE_SENSOR arriving at the requested rate, and the
     reading is within ±0.05 m of lidar_mount_height_m or below the sensor minimum
     (blind zone). Fail on no messages or a reading > lidar_mount_height_m + 0.3 m.
     The real check is the climb in step 2.
   - Camera producing frames, config valid.
1. Wait for me to flip the start switch (RC channel and threshold in config.yaml,
   read from RC_CHANNELS). Then switch to GUIDED, arm, and take off with
   MAV_CMD_NAV_TAKEOFF to takeoff_check_height_m (1.0 m) relative to home.
   Home = position at arming.
2. Climb straight up until lidar height above the floor (reading −
   lidar_mount_height_m) is within ±takeoff_check_tolerance_m (0.2 m) of 1.0 m.
   Not within takeoff_climb_timeout_s (15 s) → LAND (still over the balcony).
   Then keep climbing straight up to cruise_alt_rel_home_m (baro). No horizontal
   movement until at cruise altitude.
3. Fly in GUIDED to the box GPS coordinate at cruise altitude.
4. Descend straight down (baro) to box_ground_alt_rel_home_m + search_height_m
   (5 m). If tag 1 isn't acquired there, fly an expanding square centered on the
   box GPS coordinate at that baro altitude: leg spacing search_leg_spacing_m
   (2.5 m), max radius search_max_radius_m (5 m), speed search_speed_m_s (1 m/s).
   No rangefinder during the search. Not acquired within search_timeout_s → failed
   pickup. On acquisition: hold, then start the approach.
5. Approach. At the start, log the baro-vs-lidar height disagreement (warning only,
   above baro_lidar_warn_m). Yaw until the tag is upright, center it, then descend
   at descent_speed_m_s. Descend only while the centering error is within
   centering_tolerance_m; otherwise hold height and re-center.
   - At pickup_check_height_m (1.5 m), hold centered for pickup_check_hold_s (3 s)
     and record mean throttle ("before" sample), then continue.
   - Not at commit_height_m (0.5 m) within approach_timeout_s of acquisition →
     failed pickup.
   - Below commit height: stop requiring the tag, no horizontal corrections, descend
     straight down at final_descent_speed_m_s until contact.
6. After contact: wait magnet_settle_s, climb to pickup_check_height_m, hold for
   pickup_check_hold_s ("after" sample, attachment check, log only), then climb
   straight up to cruise altitude and fly home at cruise altitude.
7. Over home at cruise altitude, descend straight down to
   balcony_approach_alt_rel_home_m (clears the railing with margin). Acquire tag 2.
   No search pattern near the building. Run the same approach as at the box down to
   balcony_handoff_height_m above the balcony floor (no throttle hold, no commit
   phase), then switch to LAND. ArduPilot disarms on touchdown. I remove the box by
   hand.
- Failed pickup anywhere in steps 4–6 → climb straight up to cruise altitude, fly
  home at cruise altitude, then step 7 (same return path as a successful pickup).
  No retries.


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
  does after the land detector triggers, the altitude frame of the takeoff command
  (at the box the vehicle is below home, so altitudes relative to home are
  negative), and whether and how long after touchdown GUIDED would auto-disarm
  (DISARM_DELAY, throttle stick position). If it can auto-disarm, contact detection
  must trigger and start the climb well before that. Report the measured margin.
- No contact within descent_timeout_s of crossing commit height → failed pickup.
- Attachment check (logging only; the mission returns home either way):
  rise = (after − before) / before × 100, using mean VFR_HUD.throttle over the two
  pickup_check_hold_s holds at pickup_check_height_m. rise ≥
  attach_throttle_rise_pct (default 10) means "attached". Log it and send it as
  STATUSTEXT. I'll tune the threshold from test flights.


## Failsafe behavior
- "Hold" = GUIDED position target at the current position. "Hand to pilot" = switch
  to LOITER, send STATUSTEXT, stop sending commands. "Return" = climb straight up to
  cruise, fly home at cruise altitude, then step 7. This code never commands RTL.
- Mode changed by anyone but this code → stop all commands immediately, never change
  modes again, log it. (Shadow mode: log only, see docs/TESTING.md.)
- Unexpected disarm → stop, log, STATUSTEXT, never re-arm. At the box this is the
  accepted last resort: the drone stays disarmed and I recover it by hand.
- Box tag not acquired within search_timeout_s → failed pickup.
- After a tag is acquired and above commit height: tag lost for > tag_lost_hold_s
  (2 s), or rangefinder invalid → hold. Not reacquired / valid again within
  reacquire_timeout_s → failed pickup at the box, or hand to pilot at the balcony.
  Before acquisition only the search timeout applies; the descent from cruise and
  the search use baro, so rangefinder validity doesn't matter there.
- Acquisition → commit height not within approach_timeout_s → failed pickup.
- No contact within descent_timeout_s of crossing commit height → failed pickup.
- Balcony tag not acquired within balcony_tag_timeout_s → hold, then hand to pilot.
- Battery below return_v before contact → failed pickup (return). After contact →
  STATUSTEXT warning, continue home. The FC battery failsafe is the backstop.
- mission_timeout_s exceeded → return (never RTL). If already in step 7 → hand to
  pilot.
- Unhandled exception in this code → hand to pilot, then exit.
- RC loss, low battery, EKF failure → ArduPilot failsafes handle it (RTL goes to a
  rally point in open ground, not the balcony). This code sees the mode change and
  stops.
- If the Pi dies mid-flight, the drone holds position in GUIDED (velocity commands
  stop after GUID_TIMEOUT). I take over; the FC battery failsafe is the backstop.


## MAVLink notes
- The Pi sends HEARTBEAT at 1 Hz as an onboard controller: sysid 1 (same as the
  vehicle), compid 191 (MAV_COMP_ID_ONBOARD_COMPUTER).
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
- Shadow mode may send only HEARTBEAT, SET_MESSAGE_INTERVAL, parameter reads, and
  STATUSTEXT. Never arming, mode changes, takeoff, or any position/velocity command.
