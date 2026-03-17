from flask import Flask, jsonify, render_template, send_from_directory, Response
import threading
import cv2

app = Flask(__name__, template_folder='dashboard', static_folder='dashboard')

# Shared score state — updated by game logic engine, read by dashboard
score_state = {
    "serving": 0,
    "receiving": 0,
    "server": 1,
    "status": "idle",   # idle | live | stopped
    "log": []           # recent events
}
_lock = threading.Lock()
_stop_event = None


def set_stop_event(event):
    """Pass main's stop_event so the /stop route can trigger shutdown."""
    global _stop_event
    _stop_event = event


# Shared latest frame for MJPEG streaming
_frame = None
_frame_lock = threading.Lock()


def push_frame(frame):
    """Called by processing_thread to share the latest annotated frame."""
    global _frame
    with _frame_lock:
        _frame = frame.copy()


def _generate_frames():
    """Generator that yields JPEG frames for MJPEG stream."""
    while True:
        with _frame_lock:
            frame = _frame
        if frame is None:
            continue
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')


def update_score(serving, receiving, server):
    """Called by game logic engine to push a score update."""
    with _lock:
        score_state["serving"] = serving
        score_state["receiving"] = receiving
        score_state["server"] = server


def add_log(message):
    """Called by game logic engine to push a log entry."""
    with _lock:
        score_state["log"].append(message)
        score_state["log"] = score_state["log"][-50:]  # keep last 50 entries


def set_status(status):
    """Set status: 'idle', 'live', or 'stopped'."""
    with _lock:
        score_state["status"] = status


# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/score')
def score():
    with _lock:
        return jsonify(score_state)


@app.route('/video_feed')
def video_feed():
    return Response(_generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/stop', methods=['POST'])
def stop():
    if _stop_event:
        _stop_event.set()
    set_status("stopped")
    return jsonify({"status": "stopped"})


@app.route('/css/<path:filename>')
def css(filename):
    return send_from_directory('dashboard/css', filename)


@app.route('/js/<path:filename>')
def js(filename):
    return send_from_directory('dashboard/js', filename)


def run_server():
    """Run Flask in a background thread (used by main.py)."""
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
