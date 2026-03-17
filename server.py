from flask import Flask, jsonify, render_template, send_from_directory
import threading

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


@app.route('/css/<path:filename>')
def css(filename):
    return send_from_directory('dashboard/css', filename)


@app.route('/js/<path:filename>')
def js(filename):
    return send_from_directory('dashboard/js', filename)


def run_server():
    """Run Flask in a background thread (used by main.py)."""
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
