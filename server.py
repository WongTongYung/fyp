from flask import Flask, jsonify, render_template, send_from_directory, Response, request
import threading
import time
import json
import cv2
import logging

logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__, template_folder='dashboard', static_folder='dashboard')

# Shared score state — updated by game logic engine, read by dashboard
score_state = {
    "serving": 0,
    "receiving": 0,
    "server": 1,
    "server_side": "near",  # which physical side the serving team is on
    "mode": "doubles",      # "singles" or "doubles"
    "team_near": "Team A",  # name for the near-side team
    "team_far": "Team B",   # name for the far-side team
    "status": "idle",   # idle | live | stopped
    "log": [],          # recent events
    "bounces": [],      # bounce markers for top-down court view
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
_STREAM_FPS = 30                   # cap: browsers decode MJPEG in CPU, 30fps is smooth at any window size
_last_push_time = 0.0


def push_frame(frame):
    """Called by capture/processing to share the latest frame. Rate-limited to _STREAM_FPS."""
    global _frame, _last_push_time
    now = time.time()
    if now - _last_push_time < 1.0 / _STREAM_FPS:
        return   # drop this frame — too soon since last stream update
    _last_push_time = now
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


def update_score(serving, receiving, server, server_side=None):
    """Called by game logic engine to push a score update."""
    with _lock:
        score_state["serving"] = serving
        score_state["receiving"] = receiving
        score_state["server"] = server
        if server_side is not None:
            score_state["server_side"] = server_side


def add_log(message):
    """Called by game logic engine to push a log entry."""
    with _lock:
        score_state["log"].append(message)
        score_state["log"] = score_state["log"][-50:]  # keep last 50 entries


def add_bounce(court_x, court_y, result):
    """Push a bounce marker (court coords in cm) for the top-down view."""
    with _lock:
        score_state["bounces"].append({
            "court_x": round(court_x, 1),
            "court_y": round(court_y, 1),
            "result": result,
        })
        score_state["bounces"] = score_state["bounces"][-50:]


def add_serve(court_x, court_y, side):
    """Push a serve event (court coords in cm) for the top-down view."""
    with _lock:
        score_state["bounces"].append({
            "court_x": round(court_x, 1),
            "court_y": round(court_y, 1),
            "result": "SERVE",
            "side": side,
        })
        score_state["bounces"] = score_state["bounces"][-50:]


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


_SETUP_KEYS = ("serving", "receiving", "server", "server_side",
               "mode", "team_near", "team_far")


def reset_score_state(config=None):
    """Reset score_state to defaults, optionally applying setup config."""
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
    """Read setup fields under lock — called by GameState at init."""
    with _lock:
        return {k: score_state[k] for k in _SETUP_KEYS}


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
    global _pipeline_thread
    if _pipeline_thread and _pipeline_thread.is_alive():
        return jsonify({"error": "Already running"}), 409
    data = request.get_json(force=True, silent=True) or {}
    source = data.get("source", 0)
    # Extract setup config and reset state for new match
    config = {k: data[k] for k in _SETUP_KEYS if k in data}
    if "serving" in config:
        config["serving"] = int(config["serving"])
    if "receiving" in config:
        config["receiving"] = int(config["receiving"])
    if "server" in config:
        config["server"] = int(config["server"])
    reset_score_state(config)
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


@app.route('/update_score', methods=['POST'])
def update_score_route():
    """Called by the dashboard keyboard shortcuts to persist a manual score change."""
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
    """Toggle which physical side the serving team is on."""
    with _lock:
        cur = score_state["server_side"]
        score_state["server_side"] = "far" if cur == "near" else "near"
        return jsonify({"server_side": score_state["server_side"]})


@app.route('/stop', methods=['POST'])
def stop():
    if _pause_event:
        _pause_event.clear()  # clear pause before stopping threads
    if _stop_event:
        _stop_event.set()
    set_status("stopped")
    return jsonify({"status": "stopped"})


@app.route('/matches')
def matches_list():
    from database import get_all_matches
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
    from database import get_match_summary, get_match_bounces, get_match_scores
    from calibration import compute_homography, pixel_to_court
    summary = get_match_summary(match_id)
    bounces = get_match_bounces(match_id)
    scores = get_match_scores(match_id)
    court_poly = None
    H = None
    try:
        with open('court.json') as f:
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
    # Convert pixel bounce coordinates to court coordinates (cm)
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
