import threading
import time

import cv2
from flask import Flask, Response
from picamera2 import Picamera2

app = Flask(__name__)

picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (1280, 720), "format": "RGB888"}))
picam2.start()
time.sleep(2)  # let auto-exposure/white-balance settle before the first capture

frame_lock = threading.Lock()
latest_frame = None
fps = 0.0


def capture_loop():
    global latest_frame, fps
    last_ts = time.monotonic()
    while True:
        frame = picam2.capture_array()

        now = time.monotonic()
        instant_fps = 1.0 / (now - last_ts) if now > last_ts else 0.0
        last_ts = now
        fps = fps * 0.9 + instant_fps * 0.1 if fps else instant_fps  # smooth out jitter

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