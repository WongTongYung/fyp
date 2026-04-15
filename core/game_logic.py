import queue
import time
from config import RALLY_END_SEC, HISTORY_SIZE, SERVE_VELOCITY_THRESH, SERVE_FALLBACK_SEC
from core.database import log_event, log_score
from core.calibration import is_in_court, get_court_half, pixel_to_court
from core.ipc import MSG_SCORE_UPDATE, MSG_LOG, MSG_BOUNCE, MSG_SERVE


# --- Pickleball scoring rules ---
# Score format: server_score - receiver_score - server_number (1 or 2)
# Only the serving team can score a point
# Side-out: if server loses the rally, service passes to next server


class GameState:
    def __init__(self, match_id, court_container, state_queue, setup_config):
        self.match_id = match_id
        self.court_container = court_container
        self.state_queue = state_queue

        # Read setup config passed from display process
        cfg = setup_config
        self.server_score = cfg.get("serving", 0)
        self.receiver_score = cfg.get("receiving", 0)
        self.server_number = cfg.get("server", 1)
        self.server_side = cfg.get("server_side", "near")
        self.mode = cfg.get("mode", "doubles")

        # Rally tracking
        self.rally_bounces = []        # list of {"side", "in_court", "cx", "cy"}
        self.rally_active = False
        self.RALLY_END_SEC = RALLY_END_SEC

        # Ball tracking
        self.prev_cx = None
        self.prev_cy = None
        self.prev_direction_y = None   # 'up' or 'down' — used to detect bounce
        self.last_seen_time = None     # timestamp of last ball detection
        self.bounce_cooldown = 0       # prevent double-counting a bounce

        # Serve detection (velocity-based)
        self.ball_history = []              # recent positions: [(cx, cy, time), ...]
        self.HISTORY_SIZE = HISTORY_SIZE
        self.SERVE_VELOCITY_THRESH = SERVE_VELOCITY_THRESH
        self.serve_state = "WAITING"       # WAITING → SERVE_DETECTED → RALLY_ACTIVE
        self.score_cooldown_until = time.monotonic() + 5.0  # ignore first 5s (pre-game toss-backs)
        # if no serve detected after this, fall back to bounce-based rally
        self.SERVE_FALLBACK_SEC = SERVE_FALLBACK_SEC

    def _send(self, msg):
        """Send a message to the display process via state_queue (non-blocking)."""
        try:
            self.state_queue.put_nowait(msg)
        except queue.Full:
            pass

    def _get_court(self):
        """Return (court_poly, net_line, H) or (None, None, None)."""
        if self.court_container is None:
            return None, None, None
        with self.court_container["lock"]:
            return (self.court_container["poly"],
                    self.court_container.get("net"),
                    self.court_container.get("H"))

    def _get_velocity(self):
        """Calculate ball velocity from recent history.
        Returns (speed, dx, dy) where speed is pixels/frame and
        dx, dy indicate the movement direction."""
        if len(self.ball_history) < 3:
            return 0, 0, 0
        x0, y0, _ = self.ball_history[0]
        x1, y1, _ = self.ball_history[-1]
        n_frames = len(self.ball_history) - 1
        dx = (x1 - x0) / n_frames
        dy = (y1 - y0) / n_frames
        speed = (dx ** 2 + dy ** 2) ** 0.5
        return speed, dx, dy

    def _push(self, event_type, cx=None, cy=None, conf=None, notes=None):
        """Log to DB and send to display process."""
        log_event(self.match_id, event_type, cx=cx, cy=cy,
                  confidence=conf, notes=notes)
        self._send({"type": MSG_LOG, "message": f"[{event_type}] {notes or ''}"})

    def server_wins_point(self):
        self.server_score += 1
        log_score(self.match_id, self.server_score,
                  self.receiver_score, self.server_number)
        self._push("point_server",
                   notes=f"Score {self.server_score}-{self.receiver_score}-{self.server_number}")
        self._send({
            "type": MSG_SCORE_UPDATE,
            "serving": self.server_score,
            "receiving": self.receiver_score,
            "server": self.server_number,
            "server_side": self.server_side,
        })

    def side_out(self):
        """Server loses rally — switch service."""
        if self.mode == "singles" or self.server_number == 2:
            self.server_number = 1
            self.server_score, self.receiver_score = \
                self.receiver_score, self.server_score
            self.server_side = "far" if self.server_side == "near" else "near"
        else:
            self.server_number = 2
        log_score(self.match_id, self.server_score,
                  self.receiver_score, self.server_number)
        self._push("side_out",
                   notes=f"Server #{self.server_number} now serving. "
                         f"{self.server_score}-{self.receiver_score}")
        self._send({
            "type": MSG_SCORE_UPDATE,
            "serving": self.server_score,
            "receiving": self.receiver_score,
            "server": self.server_number,
            "server_side": self.server_side,
        })

    def resolve_rally(self):
        """Use the last recorded bounce to decide who won the rally."""
        if not self.rally_bounces:
            return
        if len(self.rally_bounces) < 2:
            self._push(
                "rally_ignored",
                notes=f"Only {len(self.rally_bounces)} bounce — likely not a real rally")
            self.rally_bounces = []
            self.rally_active = False
            self.serve_state = "WAITING"
            self.ball_history = []
            self.score_cooldown_until = time.monotonic() + 3.0
            return
        last = self.rally_bounces[-1]
        if last["in_court"]:
            losing_side = last["side"]
        else:
            losing_side = "far" if last["side"] == "near" else "near"

        if losing_side == self.server_side:
            self.side_out()
        else:
            self.server_wins_point()

        self.rally_bounces = []
        self.rally_active = False
        self.serve_state = "WAITING"
        self.ball_history = []
        self.score_cooldown_until = time.monotonic() + 3.0

    def process_coord(self, cx, cy, conf, predicted=False):
        """
        Called for every ball detection (real or Kalman-predicted).
        Tracks velocity for serve detection and vertical direction for bounces.
        """
        self.last_seen_time = time.monotonic()

        if self.prev_cx is not None and cx == self.prev_cx and cy == self.prev_cy:
            return

        if time.monotonic() < self.score_cooldown_until:
            self.prev_cx = cx
            self.prev_cy = cy
            return

        self.ball_history.append((cx, cy, self.last_seen_time))
        if len(self.ball_history) > self.HISTORY_SIZE:
            self.ball_history = self.ball_history[-self.HISTORY_SIZE:]

        if self.serve_state == "WAITING" and len(self.ball_history) >= 3:
            speed, _, _ = self._get_velocity()
            if speed >= self.SERVE_VELOCITY_THRESH:
                court_poly, net_line, H = self._get_court()
                if court_poly is not None:
                    ball_side = get_court_half(cx, cy, court_poly, net_line=net_line)
                    if ball_side == self.server_side:
                        self.serve_state = "SERVE_DETECTED"
                        self._push("serve_detected", cx=cx, cy=cy, conf=conf,
                                   notes=f"Serve detected from {self.server_side} side")
                        if H is not None:
                            cx_cm, cy_cm = pixel_to_court(cx, cy, H)
                            self._send({
                                "type": MSG_SERVE,
                                "court_x": cx_cm, "court_y": cy_cm,
                                "side": self.server_side,
                            })

        if self.prev_cy is not None:
            dy = cy - self.prev_cy
            direction = 'down' if dy > 0 else 'up'

            if (self.prev_direction_y == 'down'
                    and direction == 'up'
                    and self.bounce_cooldown == 0
                    and not predicted):
                bx, by = self.prev_cx, self.prev_cy
                court_poly, net_line, H = self._get_court()
                if court_poly is not None:
                    in_court = is_in_court(bx, by, court_poly)
                    result = "IN" if in_court else "OUT"
                    side = get_court_half(bx, by, court_poly, net_line=net_line)
                    cooldown_expired = time.monotonic() > self.score_cooldown_until
                    fallback = (cooldown_expired
                                and self.serve_state == "WAITING"
                                and self.score_cooldown_until > 0
                                and (time.monotonic() - self.score_cooldown_until
                                     >= self.SERVE_FALLBACK_SEC))
                    serve_ok = (self.serve_state != "WAITING"
                                or fallback
                                or self.score_cooldown_until == 0)
                    if (in_court or self.rally_active) and serve_ok:
                        self.rally_bounces.append({
                            "side": side, "in_court": in_court,
                            "cx": bx, "cy": by,
                        })
                        self.rally_active = True
                        if self.serve_state == "SERVE_DETECTED":
                            self.serve_state = "RALLY_ACTIVE"
                    if H is not None:
                        cx_cm, cy_cm = pixel_to_court(bx, by, H)
                        self._send({
                            "type": MSG_BOUNCE,
                            "court_x": cx_cm, "court_y": cy_cm,
                            "result": result,
                        })
                else:
                    result = "unknown"
                self._push("bounce", cx=bx, cy=by, conf=conf,
                           notes=f"Bounce {result} at ({bx:.0f}, {by:.0f})")
                self.bounce_cooldown = 10

            self.prev_direction_y = direction

        if self.bounce_cooldown > 0:
            self.bounce_cooldown -= 1

        self.prev_cx = cx
        self.prev_cy = cy

    def process_missing(self):
        """Called when no ball is detected (on queue timeout)."""
        if (self.rally_active
                and self.last_seen_time is not None
                and time.monotonic() - self.last_seen_time >= self.RALLY_END_SEC):
            self.resolve_rally()
        if (self.serve_state == "SERVE_DETECTED"
                and self.last_seen_time is not None
                and time.monotonic() - self.last_seen_time >= self.RALLY_END_SEC):
            self.serve_state = "WAITING"
            self.ball_history = []


def game_logic_thread(coord_queue, stop_event, match_id, court_container,
                      pause_event=None, state_queue=None, setup_config=None):
    """
    T4 — reads ball coordinates from coord_queue,
    runs game state logic, updates scoreboard and DB.
    """
    state = GameState(match_id, court_container, state_queue,
                      setup_config or {})

    while not stop_event.is_set():
        try:
            data = coord_queue.get(timeout=1)
            state.process_coord(data["cx"], data["cy"], data["conf"],
                                predicted=data.get("predicted", False))
        except queue.Empty:
            if stop_event.is_set():
                break
            if pause_event and pause_event.is_set():
                state.last_seen_time = time.monotonic()
                state.prev_cx = None
                state.prev_cy = None
                state.prev_direction_y = None
                state.ball_history = []
                continue
            state.process_missing()
            continue

