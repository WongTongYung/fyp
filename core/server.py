from flask import Flask, jsonify, render_template, send_from_directory, Response, request
import threading
import time
import json
import os
import cv2
import logging
from multiprocessing.shared_memory import SharedMemory

from core.ipc import (MSG_FRAME_READY, MSG_DETECTIONS, MSG_SCORE_UPDATE, MSG_LOG,
                      MSG_BOUNCE, MSG_SERVE, MSG_STATUS, MSG_SOURCE, MSG_FRAME_POS,
                      MSG_RESET, CMD_START, CMD_STOP, CMD_PAUSE, CMD_RESUME,
                      CMD_REWIND, CMD_RECALIBRATE, read_frame)

logging.getLogger('werkzeug').setLevel(logging.ERROR)

COURT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "court.json")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__,
            template_folder=os.path.join(_ROOT, 'dashboard'),
            static_folder=os.path.join(_ROOT, 'dashboard'))

_rewind_requested_at = 0.0

# Shared score state — updated by ipc_recv_thread, read by dashboard
score_state = {
    "serving": 0,
    "receiving": 0,
    "server": 1,
    "server_side": "near",
    "mode": "doubles",
    "team_near": "Team A",
    "team_far": "Team B",
    "status": "idle",
    "log": [],
    "bounces": [],
    "source": None,
    "frame_pos": 0,
    "fps": 30,
}
_lock = threading.Lock()

# IPC references — set by init_display_process()
_cmd_queue = None
_state_queue = None
_shm_name = None
_shm_lock = None


# --- MJPEG Streaming ---

_frame = None
_frame_lock = threading.Lock()
_frame_event = threading.Event()
_STREAM_FPS = 30
_last_push_time = 0.0

# Pre-encoded JPEG buffer
_jpeg_buffer = None
_jpeg_lock = threading.Lock()
_jpeg_event = threading.Event()


def _jpeg_encoder_thread():
    """Background thread that continuously encodes the latest frame to JPEG."""
    last_frame = None
    while True:
        _frame_event.wait(timeout=1.0)
        _frame_event.clear()
        with _frame_lock:
            frame = _frame
        if frame is None or frame is last_frame:
            continue
        last_frame = frame
        h, w = frame.shape[:2]
        max_w = 480
        if w > max_w:
            scale = max_w / w
            frame = cv2.resize(frame, (max_w, int(h * scale)))
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
        jpeg_bytes = buffer.tobytes()
        global _jpeg_buffer
        with _jpeg_lock:
            _jpeg_buffer = jpeg_bytes
        _jpeg_event.set()


def push_frame(frame):
    """Accept a frame for MJPEG streaming. Rate-limited to _STREAM_FPS."""
    global _frame, _last_push_time
    now = time.time()
    if now - _last_push_time < 1.0 / _STREAM_FPS:
        return
    _last_push_time = now
    with _frame_lock:
        _frame = frame
    _frame_event.set()


def _generate_frames():
    """Generator that yields pre-encoded JPEG frames for MJPEG stream."""
    while True:
        _jpeg_event.wait(timeout=1.0)
        _jpeg_event.clear()
        with _jpeg_lock:
            jpeg = _jpeg_buffer
        if jpeg is None:
            continue
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')


# --- Detection overlay via SSE ---
_det_data = None
_det_lock = threading.Lock()
_det_event = threading.Event()


def push_detections(detections, frame_w, frame_h, court=None, det_fps=0):
    """Push detection coordinates for browser canvas overlay via SSE."""
    global _det_data
    data = {"detections": detections, "frame_w": frame_w, "frame_h": frame_h, "fps": det_fps}
    if court is not None:
        data["court"] = court
    with _det_lock:
        _det_data = json.dumps(data)
    _det_event.set()


def _generate_detections():
    """SSE generator that yields detection JSON as events."""
    last_payload = None
    while True:
        _det_event.wait(timeout=2.0)
        _det_event.clear()
        with _det_lock:
            payload = _det_data
        if payload is None:
            yield ': keepalive\n\n'
            continue
        if payload is last_payload:
            continue
        last_payload = payload
        yield f'data: {payload}\n\n'


# --- Score state management (called locally by ipc_recv_thread) ---

def update_score(serving, receiving, server, server_side=None):
    with _lock:
        score_state["serving"] = serving
        score_state["receiving"] = receiving
        score_state["server"] = server
        if server_side is not None:
            score_state["server_side"] = server_side


def add_log(message):
    with _lock:
        score_state["log"].append(message)
        score_state["log"] = score_state["log"][-50:]


def add_bounce(court_x, court_y, result):
    with _lock:
        score_state["bounces"].append({
            "court_x": round(court_x, 1),
            "court_y": round(court_y, 1),
            "result": result,
        })
        score_state["bounces"] = score_state["bounces"][-50:]


def add_serve(court_x, court_y, side):
    with _lock:
        score_state["bounces"].append({
            "court_x": round(court_x, 1),
            "court_y": round(court_y, 1),
            "result": "SERVE",
            "side": side,
        })
        score_state["bounces"] = score_state["bounces"][-50:]


def set_status(status):
    with _lock:
        score_state["status"] = status


def set_source(source):
    with _lock:
        score_state["source"] = source if source != 0 else None


def set_frame_pos(frame_pos, fps):
    with _lock:
        score_state["frame_pos"] = frame_pos
        score_state["fps"] = fps


_SETUP_KEYS = ("serving", "receiving", "server", "server_side",
               "mode", "team_near", "team_far")


def reset_score_state(config=None):
    with _lock:
        score_state["serving"] = 0
        score_state["receiving"] = 0
        score_state["server"] = 1
        score_state["server_side"] = "near"
        score_state["mode"] = "doubles"
        score_state["team_near"] = "Team A"
        score_state["team_far"] = "Team B"
        score_state["status"] = "idle"
        score_state["log"] = []
        score_state["bounces"] = []
        score_state["frame_pos"] = 0
        if config:
            for k in _SETUP_KEYS:
                if k in config:
                    score_state[k] = config[k]


def get_setup_config():
    with _lock:
        return {k: score_state[k] for k in _SETUP_KEYS}


# --- IPC Receiver Thread ---

def _ipc_recv_thread():
    """Drains state_queue from the tracking process and updates local state."""
    import queue as _queue
    shm = SharedMemory(name=_shm_name, create=False)
    last_seq = -1
    # [DEBUG] Track IPC receive rates
    _recv_fps_counter = 0
    _recv_frame_counter = 0
    _recv_timer = time.time()

    while True:
        try:
            msg = _state_queue.get(timeout=0.5)
        except _queue.Empty:
            continue

        _recv_fps_counter += 1
        elapsed = time.time() - _recv_timer
        if elapsed >= 2.0:
            _recv_fps_counter = 0
            _recv_frame_counter = 0
            _recv_timer = time.time()

        msg_type = msg.get("type")

        if msg_type == MSG_FRAME_READY:
            seq = msg.get("seq", 0)
            if seq <= last_seq:
                continue
            last_seq = seq
            _recv_frame_counter += 1
            frame, _ = read_frame(shm, _shm_lock)
            push_frame(frame)

        elif msg_type == MSG_DETECTIONS:
            push_detections(
                msg["detections"], msg["frame_w"], msg["frame_h"],
                court=msg.get("court"), det_fps=msg.get("fps", 0)
            )

        elif msg_type == MSG_SCORE_UPDATE:
            update_score(
                msg["serving"], msg["receiving"], msg["server"],
                server_side=msg.get("server_side")
            )

        elif msg_type == MSG_LOG:
            add_log(msg["message"])

        elif msg_type == MSG_BOUNCE:
            add_bounce(msg["court_x"], msg["court_y"], msg["result"])

        elif msg_type == MSG_SERVE:
            add_serve(msg["court_x"], msg["court_y"], msg["side"])

        elif msg_type == MSG_STATUS:
            set_status(msg["status"])

        elif msg_type == MSG_SOURCE:
            set_source(msg["source"])

        elif msg_type == MSG_FRAME_POS:
            set_frame_pos(msg["frame_pos"], msg["fps"])

        elif msg_type == MSG_RESET:
            reset_score_state(msg.get("config"))


# --- IPC Initialization ---

def init_display_process(cmd_queue, state_queue, shm_name, shm_lock):
    """Initialize IPC references and start background threads. Called once in display process."""
    global _cmd_queue, _state_queue, _shm_name, _shm_lock
    _cmd_queue = cmd_queue
    _state_queue = state_queue
    _shm_name = shm_name
    _shm_lock = shm_lock

    # Start JPEG encoder thread
    encoder_t = threading.Thread(target=_jpeg_encoder_thread, daemon=True)
    encoder_t.start()

    # Start IPC receiver thread
    recv_t = threading.Thread(target=_ipc_recv_thread, daemon=True)
    recv_t.start()


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


@app.route('/detections')
def detections_feed():
    return Response(_generate_detections(),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/start', methods=['POST'])
def start():
    # Check if already running
    with _lock:
        if score_state["status"] == "live":
            return jsonify({"error": "Already running"}), 409

    data = request.get_json(force=True, silent=True) or {}
    source = data.get("source", 0)

    # Extract setup config
    config = {k: data[k] for k in _SETUP_KEYS if k in data}
    if "serving" in config:
        config["serving"] = int(config["serving"])
    if "receiving" in config:
        config["receiving"] = int(config["receiving"])
    if "server" in config:
        config["server"] = int(config["server"])

    # Reset local state
    reset_score_state(config)

    # Send start command to tracking process
    if _cmd_queue:
        _cmd_queue.put({"type": CMD_START, "source": source, "config": config})
        return jsonify({"status": "started"})
    return jsonify({"error": "No IPC queue"}), 500


@app.route('/pause', methods=['POST'])
def pause():
    if _cmd_queue:
        _cmd_queue.put({"type": CMD_PAUSE})
    set_status("paused")
    return jsonify({"status": "paused"})


@app.route('/rewind', methods=['POST'])
def rewind():
    global _rewind_requested_at
    if _cmd_queue:
        _cmd_queue.put({"type": CMD_REWIND})
    _rewind_requested_at = time.time()
    set_status("paused")
    return jsonify({"status": "paused"})


@app.route('/rewind_status')
def rewind_status():
    """Check if the rewind clip has been written (file modified after request)."""
    clip_path = os.path.join(_ROOT, 'styles', 'rewind', 'rewind_clip.bin')
    ready = False
    if os.path.exists(clip_path):
        mtime = os.path.getmtime(clip_path)
        ready = mtime >= _rewind_requested_at
    return jsonify({"ready": ready})


@app.route('/rewind_feed')
def rewind_feed():
    """Stream the rewind clip as MJPEG — no codec issues, works in any browser."""
    import struct

    clip_path = os.path.join(_ROOT, 'styles', 'rewind', 'rewind_clip.bin')
    if not os.path.exists(clip_path):
        return jsonify({"error": "No rewind clip"}), 404

    def generate():
        with open(clip_path, 'rb') as f:
            header = f.read(8)
            count, fps = struct.unpack('<II', header)
            delay = 1.0 / fps if fps > 0 else 1.0 / 30
            for _ in range(count):
                size_data = f.read(4)
                if not size_data:
                    break
                size = struct.unpack('<I', size_data)[0]
                jpeg = f.read(size)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')
                time.sleep(delay)

    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/resume', methods=['POST'])
def resume():
    if _cmd_queue:
        _cmd_queue.put({"type": CMD_RESUME})
    set_status("live")
    return jsonify({"status": "live"})


@app.route('/update_score', methods=['POST'])
def update_score_route():
    data = request.get_json(force=True, silent=True) or {}
    with _lock:
        score_state["serving"]   = int(data.get("serving",  score_state["serving"]))
        score_state["receiving"] = int(data.get("receiving", score_state["receiving"]))
        score_state["server"]    = int(data.get("server",    score_state["server"]))
        msg = data.get("log")
        if msg:
            score_state["log"].append(msg)
            score_state["log"] = score_state["log"][-50:]
    return jsonify({"status": "ok"})


@app.route('/swap_side', methods=['POST'])
def swap_side():
    with _lock:
        cur = score_state["server_side"]
        score_state["server_side"] = "far" if cur == "near" else "near"
        return jsonify({"server_side": score_state["server_side"]})


@app.route('/stop', methods=['POST'])
def stop():
    if _cmd_queue:
        _cmd_queue.put({"type": CMD_STOP})
    set_status("stopped")
    return jsonify({"status": "stopped"})


@app.route('/matches')
def matches_list():
    from core.database import get_all_matches
    from datetime import datetime
    matches = get_all_matches()
    rows = ""
    for m in matches:
        duration = "—"
        if m.get("started_at") and m.get("ended_at"):
            try:
                s = datetime.fromisoformat(m["started_at"])
                e = datetime.fromisoformat(m["ended_at"])
                secs = int((e - s).total_seconds())
                duration = f"{secs // 60}m {secs % 60}s"
            except Exception:
                pass
        rows += (
            f'<tr><td>#{m["id"]}</td>'
            f'<td>{m["started_at"][:19]}</td>'
            f'<td>{duration}</td>'
            f'<td><a href="/analysis/{m["id"]}">View Analysis</a></td></tr>'
        )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Match History</title>
<link rel="stylesheet" href="/css/style.css">
<style>
  table{{width:100%;border-collapse:collapse;margin-top:15px;}}
  th,td{{padding:10px 14px;border:1px solid #333;text-align:left;}}
  th{{background:#f5f5f5;font-weight:bold;}}
  a{{color:#1565c0;text-decoration:none;}}
  a:hover{{text-decoration:underline;}}
  .back{{font-size:14px;border:2px solid #333;padding:4px 12px;color:#333;}}
</style></head>
<body>
<header class="header"><h1>PICKLEBALL POINT COUNTING SYSTEM</h1></header>
<div style="padding:10px 20px;">
  <a href="/" class="back">← Dashboard</a>
  <h2 style="margin:15px 0;font-size:20px;font-weight:bold;">Match History</h2>
  <table>
    <thead><tr><th>Match</th><th>Started</th><th>Duration</th><th>Analysis</th></tr></thead>
    <tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;color:#999;">No matches recorded yet.</td></tr>'}</tbody>
  </table>
</div></body></html>"""
    return html


@app.route('/analysis/<int:match_id>')
def analysis_page(match_id):
    return render_template('analysis.html', match_id=match_id)


@app.route('/api/analysis/<int:match_id>')
def analysis_data(match_id):
    import json as _json
    import numpy as np
    from core.database import get_match_summary, get_match_bounces, get_match_scores
    from core.calibration import compute_homography, pixel_to_court
    summary = get_match_summary(match_id)
    bounces = get_match_bounces(match_id)
    scores = get_match_scores(match_id)
    court_poly = None
    H = None
    try:
        with open(COURT_FILE) as f:
            raw = _json.load(f)
        if isinstance(raw, dict):
            court_poly = raw.get("corners")
            net = raw.get("net")
        else:
            court_poly = raw
            net = None
        if court_poly:
            H = compute_homography(np.array(court_poly, dtype=np.float32),
                                   net=np.array(net, dtype=np.float32) if net else None)
    except Exception:
        pass
    if H is not None:
        for b in bounces:
            if b.get("cx") is not None and b.get("cy") is not None:
                cx_cm, cy_cm = pixel_to_court(b["cx"], b["cy"], H)
                b["court_x"] = round(cx_cm, 1)
                b["court_y"] = round(cy_cm, 1)
                b["result"] = "OUT" if (b.get("notes") and "OUT" in b["notes"]) else "IN"
    return jsonify({
        "match": summary["match"],
        "stats": summary["stats"],
        "bounces": bounces,
        "scores": scores,
        "court_poly": court_poly,
    })


@app.route('/calibrate/frame')
def calibrate_frame():
    """Return a full-resolution JPEG snapshot from the live feed for calibration."""
    with _frame_lock:
        frame = _frame
    if frame is None:
        return jsonify({"error": "No frame available"}), 404
    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return Response(buffer.tobytes(), mimetype='image/jpeg')


@app.route('/calibrate/save', methods=['POST'])
def calibrate_save():
    """Save 6 clicked calibration points (4 corners + 2 net) to court.json."""
    data = request.get_json(force=True, silent=True) or {}
    corners = data.get("corners")
    net = data.get("net")
    if not corners or len(corners) != 4:
        return jsonify({"error": "Need exactly 4 corner points"}), 400
    if not net or len(net) != 2:
        return jsonify({"error": "Need exactly 2 net points"}), 400
    payload = {"corners": corners, "net": net}
    with open(COURT_FILE, "w") as f:
        json.dump(payload, f)
    # Notify tracking process to reload court from file
    if _cmd_queue:
        _cmd_queue.put({"type": CMD_RECALIBRATE})
    return jsonify({"status": "saved"})


@app.route('/calibrate/load')
def calibrate_load():
    """Load existing calibration from court.json if it exists."""
    if not os.path.exists(COURT_FILE):
        return jsonify({"exists": False})
    with open(COURT_FILE, "r") as f:
        data = json.load(f)
    return jsonify({"exists": True, "corners": data.get("corners"), "net": data.get("net")})


@app.route('/styles/<path:filename>')
def styles(filename):
    mime = 'video/mp4' if filename.endswith('.mp4') else None
    resp = send_from_directory(os.path.join(_ROOT, 'styles'), filename, mimetype=mime)
    if filename.endswith('.mp4'):
        resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/css/<path:filename>')
def css(filename):
    return send_from_directory(os.path.join(_ROOT, 'dashboard', 'css'), filename)


@app.route('/js/<path:filename>')
def js(filename):
    return send_from_directory(os.path.join(_ROOT, 'dashboard', 'js'), filename)


def run_server():
    """Run Flask — called in the display process."""
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
