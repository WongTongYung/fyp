import queue
import time
from database import log_event, log_score
from server import update_score, add_log, get_setup_config, add_bounce, add_serve
from calibration import is_in_court, get_court_half, pixel_to_court


# --- Pickleball scoring rules ---
# Score format: server_score - receiver_score - server_number (1 or 2)
# Only the serving team can score a point
# Side-out: if server loses the rally, service passes to next server


class GameState:
    def __init__(self, match_id, court_container):
        self.match_id = match_id
        self.court_container = court_container

        # Read setup config from dashboard (set before Start)
        cfg = get_setup_config()
        self.server_score = cfg["serving"]
        self.receiver_score = cfg["receiving"]
        self.server_number = cfg["server"]
        self.server_side = cfg["server_side"]
        self.mode = cfg["mode"]           # "singles" or "doubles"

        # Rally tracking
        self.rally_bounces = []        # list of {"side", "in_court", "cx", "cy"}
        self.rally_active = False
        self.RALLY_END_SEC = 2.0       # seconds with no ball = rally over

        # Ball tracking
        self.prev_cx = None
        self.prev_cy = None
        self.prev_direction_y = None   # 'up' or 'down' — used to detect bounce
        self.last_seen_time = None     # timestamp of last ball detection
        self.bounce_cooldown = 0       # prevent double-counting a bounce

        # Serve detection (velocity-based)
        self.ball_history = []              # recent positions: [(cx, cy, time), ...]
        self.HISTORY_SIZE = 5              # keep last N detections
        self.SERVE_VELOCITY_THRESH = 120   # pixels/frame displacement to trigger serve
        self.serve_state = "WAITING"       # WAITING → SERVE_DETECTED → RALLY_ACTIVE
        self.score_cooldown_until = time.monotonic() + 5.0  # ignore first 5s (pre-game toss-backs)
        self.SERVE_FALLBACK_SEC = 10       # if no serve detected after this, fall back to bounce-based rally

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
        # Use first and last entries for average velocity
        x0, y0, _ = self.ball_history[0]
        x1, y1, _ = self.ball_history[-1]
        n_frames = len(self.ball_history) - 1
        dx = (x1 - x0) / n_frames
        dy = (y1 - y0) / n_frames
        speed = (dx ** 2 + dy ** 2) ** 0.5
        return speed, dx, dy

    def _push(self, event_type, cx=None, cy=None, conf=None, notes=None):
        """Log to DB and dashboard. Does NOT push score — call update_score() only when score changes."""
        log_event(self.match_id, event_type, cx=cx, cy=cy,
                  confidence=conf, notes=notes)
        add_log(f"[{event_type}] {notes or ''}")

    def server_wins_point(self):
        self.server_score += 1
        log_score(self.match_id, self.server_score,
                  self.receiver_score, self.server_number)
        self._push("point_server",
                   notes=f"Score {self.server_score}-{self.receiver_score}-{self.server_number}")
        update_score(self.server_score, self.receiver_score, self.server_number,
                     self.server_side)

    def side_out(self):
        """Server loses rally — switch service."""
        if self.mode == "singles" or self.server_number == 2:
            # Full side-out: service goes to other team
            self.server_number = 1
            self.server_score, self.receiver_score = \
                self.receiver_score, self.server_score
            self.server_side = "far" if self.server_side == "near" else "near"
        else:
            # Doubles: first server done, move to second server
            self.server_number = 2
        log_score(self.match_id, self.server_score,
                  self.receiver_score, self.server_number)
        self._push("side_out",
                   notes=f"Server #{self.server_number} now serving. "
                         f"{self.server_score}-{self.receiver_score}")
        update_score(self.server_score, self.receiver_score, self.server_number,
                     self.server_side)

    def resolve_rally(self):
        """Use the last recorded bounce to decide who won the rally."""
        if not self.rally_bounces:
            return
        # Ignore rallies with only 1 bounce — likely a hand toss/pass,
        # not a real rally. A real serve rally has at least 2 bounces
        # (serve lands + return or serve lands + ball dies).
        if len(self.rally_bounces) < 2:
            self._push("rally_ignored",
                        notes=f"Only {len(self.rally_bounces)} bounce — likely not a real rally")
            self.rally_bounces = []
            self.rally_active = False
            self.serve_state = "WAITING"
            self.ball_history = []
            self.score_cooldown_until = time.monotonic() + 3.0
            return
        last = self.rally_bounces[-1]
        if last["in_court"]:
            # Ball landed IN on this side and wasn't returned — that side loses
            losing_side = last["side"]
        else:
            # Ball went OUT — the team that hit it (opposite side) loses
            losing_side = "far" if last["side"] == "near" else "near"

        if losing_side == self.server_side:
            self.side_out()
        else:
            self.server_wins_point()

        self.rally_bounces = []
        self.rally_active = False
        self.serve_state = "WAITING"
        self.ball_history = []
        self.score_cooldown_until = time.monotonic() + 3.0  # ignore toss-backs for 3s

    def process_coord(self, cx, cy, conf):
        """
        Called for every ball detection.
        Tracks velocity for serve detection and vertical direction for bounces.
        """
        self.last_seen_time = time.monotonic()

        # Skip duplicate detections — same position provides no direction info
        if self.prev_cx is not None and cx == self.prev_cx and cy == self.prev_cy:
            return

        # --- Serve detection via velocity spike ---
        # Skip all detection during post-score cooldown
        if time.monotonic() < self.score_cooldown_until:
            self.prev_cx = cx
            self.prev_cy = cy
            return

        self.ball_history.append((cx, cy, self.last_seen_time))
        if len(self.ball_history) > self.HISTORY_SIZE:
            self.ball_history = self.ball_history[-self.HISTORY_SIZE:]

        if self.serve_state == "WAITING" and len(self.ball_history) >= 3:
            speed, dx, dy = self._get_velocity()
            if speed >= self.SERVE_VELOCITY_THRESH:
                court_poly, net_line, H = self._get_court()
                if court_poly is not None:
                    ball_side = get_court_half(cx, cy, court_poly, net_line=net_line)
                    # Ball should be on or near the server's side when serve starts
                    if ball_side == self.server_side:
                        self.serve_state = "SERVE_DETECTED"
                        self._push("serve_detected", cx=cx, cy=cy, conf=conf,
                                   notes=f"Serve detected from {self.server_side} side")
                        if H is not None:
                            cx_cm, cy_cm = pixel_to_court(cx, cy, H)
                            add_serve(cx_cm, cy_cm, self.server_side)

        if self.prev_cy is not None:
            dy = cy - self.prev_cy          # positive = moving down, negative = moving up
            direction = 'down' if dy > 0 else 'up'

            # Bounce: ball was going down and is now going up.
            # Use prev_cx/prev_cy (last frame still going down) as the bounce
            # position — it is closer to the actual ground contact point than
            # the current frame where the ball has already started rising.
            if (self.prev_direction_y == 'down'
                    and direction == 'up'
                    and self.bounce_cooldown == 0):
                bx, by = self.prev_cx, self.prev_cy
                court_poly, net_line, H = self._get_court()
                if court_poly is not None:
                    in_court = is_in_court(bx, by, court_poly)
                    result = "IN" if in_court else "OUT"
                    side = get_court_half(bx, by, court_poly, net_line=net_line)
                    # Only start tracking a rally after a serve is detected.
                    # Fallback: if no serve detected for SERVE_FALLBACK_SEC after
                    # cooldown, allow bounce-based rally start (original behavior)
                    # so the system never gets stuck.
                    cooldown_expired = time.monotonic() > self.score_cooldown_until
                    fallback = (cooldown_expired
                                and self.serve_state == "WAITING"
                                and self.score_cooldown_until > 0
                                and time.monotonic() - self.score_cooldown_until >= self.SERVE_FALLBACK_SEC)
                    serve_ok = self.serve_state != "WAITING" or fallback or self.score_cooldown_until == 0
                    if (in_court or self.rally_active) and serve_ok:
                        self.rally_bounces.append({
                            "side": side, "in_court": in_court,
                            "cx": bx, "cy": by,
                        })
                        self.rally_active = True
                        if self.serve_state == "SERVE_DETECTED":
                            self.serve_state = "RALLY_ACTIVE"
                    # Push bounce to top-down court view
                    if H is not None:
                        cx_cm, cy_cm = pixel_to_court(bx, by, H)
                        add_bounce(cx_cm, cy_cm, result)
                else:
                    result = "unknown"
                self._push("bounce", cx=bx, cy=by, conf=conf,
                           notes=f"Bounce {result} at ({bx:.0f}, {by:.0f})")
                self.bounce_cooldown = 10   # skip next 10 frames before counting again

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
        # Reset serve detection if ball disappears for too long without a rally
        if (self.serve_state == "SERVE_DETECTED"
                and self.last_seen_time is not None
                and time.monotonic() - self.last_seen_time >= self.RALLY_END_SEC):
            self.serve_state = "WAITING"
            self.ball_history = []


def game_logic_thread(coord_queue, stop_event, match_id, court_container,
                      pause_event=None):
    """
    T4 — reads ball coordinates from coord_queue,
    runs game state logic, updates scoreboard and DB.
    """
    print("Starting game logic thread...")
    state = GameState(match_id, court_container)

    while not stop_event.is_set():
        try:
            data = coord_queue.get(timeout=1)
            state.process_coord(data["cx"], data["cy"], data["conf"])
        except queue.Empty:
            if stop_event.is_set():
                break
            # Don't resolve rallies while paused/stopped — ball disappearance
            # is not a real rally end, just the camera being paused.
            if pause_event and pause_event.is_set():
                # Freeze — don't resolve rallies or clear state while paused
                state.last_seen_time = time.monotonic()
                # Reset ball tracking so resume starts with fresh direction data
                state.prev_cx = None
                state.prev_cy = None
                state.prev_direction_y = None
                state.ball_history = []
                continue
            state.process_missing()
            continue

    print("Game logic thread stopped.")
