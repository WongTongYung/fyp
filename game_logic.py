import queue
import time
from database import log_event, log_score
from server import update_score, add_log, get_setup_config
from calibration import is_in_court, get_court_half


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

    def _get_court(self):
        """Return (court_poly, net_line) or (None, None)."""
        if self.court_container is None:
            return None, None
        with self.court_container["lock"]:
            return self.court_container["poly"], self.court_container.get("net")

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

    def process_coord(self, cx, cy, conf):
        """
        Called for every ball detection.
        Tracks vertical direction to detect bounces.
        """
        self.last_seen_time = time.monotonic()

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
                court_poly, net_line = self._get_court()
                if court_poly is not None:
                    in_court = is_in_court(bx, by, court_poly)
                    result = "IN" if in_court else "OUT"
                    side = get_court_half(bx, by, court_poly, net_line=net_line)
                    self.rally_bounces.append({
                        "side": side, "in_court": in_court,
                        "cx": bx, "cy": by,
                    })
                    self.rally_active = True
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


def game_logic_thread(coord_queue, stop_event, match_id, court_container):
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
            state.process_missing()
            continue

    print("Game logic thread stopped.")
