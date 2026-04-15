import os

_ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Model Paths ---
BALL_MODEL_PATH = "models/best26m-improved3.pt"
TRAINING_DATA_PATH = "training/pickleball.v1i.yolo26_combined/data.yaml"

# --- Data Paths ---
DB_PATH = os.path.join(_ROOT, "data", "pickleball.db")
COURT_FILE = os.path.join(_ROOT, "data", "court.json")

# --- Court Dimensions (cm) ---
# Standard pickleball court: 609.6cm wide x 1341.12cm long
COURT_W = 609.6
COURT_L = 1341.12
NET_Y = COURT_L / 2       # Net position — halfway along court length

# --- Streaming ---
STREAM_FPS = 30          # MJPEG stream frame rate sent to browser
REWIND_BUF_SEC = 15      # rolling buffer size for the rewind clip (seconds)

# --- Ball Tracking ---
MAX_PREDICT_FRAMES = 5   # Kalman filter: stop predicting after N consecutive misses

# --- Game Logic ---
RALLY_END_SEC = 2.0          # seconds with no ball before rally is considered over
HISTORY_SIZE = 5             # recent positions kept for velocity calculation
SERVE_VELOCITY_THRESH = 120  # pixels/frame displacement to trigger serve detection
SERVE_FALLBACK_SEC = 10      # seconds before falling back to bounce-based rally
