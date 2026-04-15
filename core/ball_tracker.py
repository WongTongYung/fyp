import numpy as np

from config import MAX_PREDICT_FRAMES


class BallKalmanTracker:
    """
    Constant-velocity Kalman filter for 2D ball tracking.
    State: [x, y, vx, vy]
    Measurement: [x, y]

    Bridges short detection gaps (1-5 frames) with predicted positions
    and smooths noisy YOLO detections for more stable bounce/velocity detection.
    """

    def __init__(self, dt=1.0, process_noise=100.0, measurement_noise=5.0):
        self.dt = dt
        self.initialized = False
        self.miss_count = 0

        # State transition matrix F (constant velocity model)
        # x'  = x + vx*dt
        # y'  = y + vy*dt
        # vx' = vx
        # vy' = vy
        self.F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1,  0],
            [0, 0, 0,  1],
        ], dtype=np.float64)

        # Measurement matrix H (we observe x, y only)
        self.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
        ], dtype=np.float64)

        # Process noise covariance Q
        self.Q = np.eye(4, dtype=np.float64) * process_noise

        # Measurement noise covariance R
        self.R = np.eye(2, dtype=np.float64) * measurement_noise

        # State estimate and covariance
        self.x = np.zeros(4, dtype=np.float64)
        self.P = np.eye(4, dtype=np.float64) * 500.0

    def _predict(self):
        """Predict next state from current state + velocity."""
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q

    def _update(self, z):
        """Update state estimate with a real measurement."""
        y = z - self.H @ self.x                        # innovation
        S = self.H @ self.P @ self.H.T + self.R        # innovation covariance
        K = self.P @ self.H.T @ np.linalg.inv(S)       # Kalman gain
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P

    def process_detection(self, cx, cy, conf):
        """Called when YOLO detects the ball. Returns filtered (cx, cy)."""
        z = np.array([cx, cy], dtype=np.float64)

        if not self.initialized:
            self.x = np.array([cx, cy, 0.0, 0.0], dtype=np.float64)
            self.P = np.eye(4, dtype=np.float64) * 500.0
            self.initialized = True
            self.miss_count = 0
            return cx, cy  # first detection: return raw

        self._predict()
        self._update(z)
        self.miss_count = 0
        return float(self.x[0]), float(self.x[1])

    def process_miss(self):
        """Called when YOLO misses. Returns predicted (cx, cy) or None."""
        if not self.initialized:
            return None

        self.miss_count += 1
        if self.miss_count > MAX_PREDICT_FRAMES:
            return None  # too many consecutive misses — stop predicting

        self._predict()
        return float(self.x[0]), float(self.x[1])

    def reset(self):
        """Reset the filter (e.g. after a long gap or new rally)."""
        self.initialized = False
        self.miss_count = 0
        self.x = np.zeros(4, dtype=np.float64)
        self.P = np.eye(4, dtype=np.float64) * 500.0
