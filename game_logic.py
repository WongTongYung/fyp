import queue
from database import log_event, log_score
from server import update_score, add_log
from calibration import is_in_court


# --- Pickleball scoring rules ---
# Score format: server_score - receiver_score - server_number (1 or 2)
# Only the serving team can score a point
# Side-out: if server loses the rally, service passes to next server


class GameState:
    def __init__(self, match_id, court_container):
        self.match_id = match_id
        self.court_container = court_container

        # Scores
        self.server_score = 0
        self.receiver_score = 0
        self.server_number = 1      # 1 or 2 (in doubles, each team has 2 servers)

        # Ball tracking
        self.prev_cx = None
        self.prev_cy = None
        self.prev_direction_y = None   # 'up' or 'down' — used to detect bounce
        self.frames_missing = 0        # consecutive frames with no ball detected
        self.bounce_cooldown = 0       # prevent double-counting a bounce

    def _get_court(self):
        if self.court_container is None:
            return None
        with self.court_container["lock"]:
            return self.court_container["poly"]

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
        update_score(self.server_score, self.receiver_score, self.server_number)

    def side_out(self):
        """Server loses rally — switch service."""
        if self.server_number == 1:
            self.server_number = 2
        else:
            # Both servers used — service goes to other team
            self.server_number = 1
            # Swap server/receiver scores
            self.server_score, self.receiver_score = \
                self.receiver_score, self.server_score
        log_score(self.match_id, self.server_score,
                  self.receiver_score, self.server_number)
        self._push("side_out",
                   notes=f"Server #{self.server_number} now serving. "
                         f"{self.server_score}-{self.receiver_score}")
        update_score(self.server_score, self.receiver_score, self.server_number)

    def process_coord(self, cx, cy, conf):
        """
        Called for every ball detection.
        Tracks vertical direction to detect bounces.
        """
        self.frames_missing = 0

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
                court_poly = self._get_court()
                if court_poly is not None:
                    in_court = is_in_court(bx, by, court_poly)
                    result = "IN" if in_court else "OUT"
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
        """Called when no ball is detected in a frame."""
        self.frames_missing += 1


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
