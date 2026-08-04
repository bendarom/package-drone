import threading
import time

import cv2
from flask import Flask, Response
from picamera2 import Picamera2

app = Flask(__name__)

FRAME_SIZE = (1280, 720)
FRAME_CENTER = (FRAME_SIZE[0] // 2, FRAME_SIZE[1] // 2)

# Proportional gain and clamp for the pixel-offset -> velocity conversion.
# Output is normalized to [-1, 1]; a tag right at the frame edge saturates it.
VELOCITY_GAIN = 1.0
MAX_VELOCITY = 1.0

picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": FRAME_SIZE, "format": "RGB888"}))
picam2.start()
time.sleep(2)  # let auto-exposure/white-balance settle before the first capture

aruco_dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
aruco_detector = cv2.aruco.ArucoDetector(aruco_dictionary, cv2.aruco.DetectorParameters())

frame_lock = threading.Lock()
latest_frame = None
fps = 0.0


def detect_tag_offset(frame):
    """Detect the first AprilTag in frame and return (corners, offset_x, offset_y).

    Offset is tag-center-minus-frame-center in pixels; corners is None if no tag found.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = aruco_detector.detectMarkers(gray)
    if ids is None or len(ids) == 0:
        return None, None, 0.0, 0.0

    tag_corners = corners[0][0]
    tag_id = int(ids[0][0])
    tag_center = tag_corners.mean(axis=0)
    offset_x = tag_center[0] - FRAME_CENTER[0]
    offset_y = tag_center[1] - FRAME_CENTER[1]
    return tag_id, tag_corners, offset_x, offset_y


def offset_to_velocity(offset_x, offset_y):
    """Convert a pixel offset from center into a normalized velocity correction vector."""
    vx = VELOCITY_GAIN * offset_x / FRAME_CENTER[0]
    vy = VELOCITY_GAIN * offset_y / FRAME_CENTER[1]
    vx = max(-MAX_VELOCITY, min(MAX_VELOCITY, vx))
    vy = max(-MAX_VELOCITY, min(MAX_VELOCITY, vy))
    return vx, vy


def draw_tag_overlay(frame, tag_id, tag_corners, offset_x, offset_y, vx, vy):
    cx, cy = FRAME_CENTER
    cv2.drawMarker(frame, (cx, cy), (255, 255, 255), cv2.MARKER_CROSS, 20, 1)

    if tag_corners is None:
        cv2.putText(frame, "No tag detected", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return

    tag_center = tag_corners.mean(axis=0)
    tcx, tcy = int(tag_center[0]), int(tag_center[1])

    pts = tag_corners.astype(int).reshape((-1, 1, 2))
    cv2.polylines(frame, [pts], True, (0, 255, 0), 2)
    cv2.circle(frame, (tcx, tcy), 5, (0, 255, 0), -1)
    cv2.line(frame, (cx, cy), (tcx, tcy), (0, 255, 255), 2)

    arrow_len = 150  # pixels per unit of normalized velocity
    tip = (int(cx + vx * arrow_len), int(cy + vy * arrow_len))
    cv2.arrowedLine(frame, (cx, cy), tip, (0, 0, 255), 3, tipLength=0.3)

    cv2.putText(frame, f"id {tag_id} dx {offset_x:+.0f}px dy {offset_y:+.0f}px", (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(frame, f"vx {vx:+.2f} vy {vy:+.2f}", (10, 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)


def capture_loop():
    global latest_frame, fps
    last_ts = time.monotonic()
    while True:
        frame = picam2.capture_array()

        now = time.monotonic()
        instant_fps = 1.0 / (now - last_ts) if now > last_ts else 0.0
        last_ts = now
        fps = fps * 0.9 + instant_fps * 0.1 if fps else instant_fps  # smooth out jitter

        tag_id, tag_corners, offset_x, offset_y = detect_tag_offset(frame)
        vx, vy = offset_to_velocity(offset_x, offset_y)
        draw_tag_overlay(frame, tag_id, tag_corners, offset_x, offset_y, vx, vy)

        cv2.putText(frame, f"{fps:.1f} FPS", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        ok, jpeg = cv2.imencode(".jpg", frame)
        if ok:
            with frame_lock:
                latest_frame = jpeg.tobytes()


def mjpeg_generator():
    while True:
        with frame_lock:
            frame = latest_frame
        if frame is None:
            time.sleep(0.05)
            continue
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")


@app.route("/")
def index():
    return """
    <html>
      <head><title>Drone Camera</title></head>
      <body style="margin:0;background:#000;">
        <img src="/stream" style="width:100%;height:100vh;object-fit:contain;">
      </body>
    </html>
    """


@app.route("/stream")
def stream():
    return Response(mjpeg_generator(), mimetype="multipart/x-mixed-replace; boundary=frame")


if __name__ == "__main__":
    threading.Thread(target=capture_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True) #Hello World