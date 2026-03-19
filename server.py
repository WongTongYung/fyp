from flask import Flask, jsonify, render_template, send_from_directory, Response, request
import threading
import cv2
import logging

logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__, template_folder='dashboard', static_folder='dashboard')

# Shared score state — updated by game logic engine, read by dashboard
score_state = {
    "serving": 0,
    "receiving": 0,
    "server": 1,
    "status": "idle",   # idle | live | stopped
    "log": [],          # recent events
    "source": None,     # current video source path (None for webcam)
    "frame_pos": 0,     # current frame index in the video
    "fps": 30,          # fps of the current source
}
_lock = threading.Lock()
_stop_event = None
_pause_event = None
_start_callback = None
_pipeline_thread = None


def set_stop_event(event):
    global _stop_event
    _stop_event = event


def set_pause_event(event):
    global _pause_event
    _pause_event = event


def set_start_callback(cb):
    global _start_callback
    _start_callback = cb


# Shared latest frame for MJPEG streaming
_frame = None
_frame_lock = threading.Lock()
_frame_event = threading.Event()   # signals when a new frame is available


def push_frame(frame):
    """Called by processing_thread to share the latest annotated frame."""
    global _frame
    with _frame_lock:
        _frame = frame
    _frame_event.set()   # wake up the stream generator


def _generate_frames():
    """Generator that yields JPEG frames for MJPEG stream."""
    last_frame = None
    while True:
        _frame_event.wait(timeout=1.0)   # sleep until a new frame arrives
        _frame_event.clear()
        with _frame_lock:
            frame = _frame
        if frame is None or frame is last_frame:
            continue
        last_frame = frame
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


def set_source(source):
    """Store the current source path so dashboard can use it for rewind."""
    with _lock:
        score_state["source"] = source if source != 0 else None


def set_frame_pos(frame_pos, fps):
    """Called by capture_thread to report current playback position."""
    with _lock:
        score_state["frame_pos"] = frame_pos
        score_state["fps"] = fps


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


@app.route('/start', methods=['POST'])
def start():
    global _pipeline_thread
    if _pipeline_thread and _pipeline_thread.is_alive():
        return jsonify({"error": "Already running"}), 409
    data = request.get_json(force=True, silent=True) or {}
    source = data.get("source", 0)
    if _start_callback:
        _pipeline_thread = threading.Thread(target=_start_callback, args=(source,), daemon=True)
        _pipeline_thread.start()
        return jsonify({"status": "started"})
    return jsonify({"error": "No pipeline registered"}), 500


@app.route('/pause', methods=['POST'])
def pause():
    if _pause_event:
        _pause_event.set()
    set_status("paused")
    return jsonify({"status": "paused"})


@app.route('/resume', methods=['POST'])
def resume():
    if _pause_event:
        _pause_event.clear()
    set_status("live")
    return jsonify({"status": "live"})


@app.route('/stop', methods=['POST'])
def stop():
    if _pause_event:
        _pause_event.clear()  # clear pause before stopping threads
    if _stop_event:
        _stop_event.set()
    set_status("stopped")
    return jsonify({"status": "stopped"})


@app.route('/styles/<path:filename>')
def styles(filename):
    mime = 'video/mp4' if filename.endswith('.mp4') else None
    return send_from_directory('styles', filename, mimetype=mime)


@app.route('/css/<path:filename>')
def css(filename):
    return send_from_directory('dashboard/css', filename)


@app.route('/js/<path:filename>')
def js(filename):
    return send_from_directory('dashboard/js', filename)


def run_server():
    """Run Flask in a background thread (used by main.py)."""
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
