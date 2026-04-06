"""
IPC protocol for the 2-process architecture.

Process 1 (Tracking) communicates with Process 2 (Display) via:
  - shared memory for raw video frames (high bandwidth)
  - state_queue (Tracking → Display) for scores, logs, detections, etc.
  - cmd_queue (Display → Tracking) for start/stop/pause/resume commands
"""
import struct
import numpy as np

# --- Shared memory layout ---
# Bytes 0-3:   uint32  sequence number
# Bytes 4-7:   uint32  height
# Bytes 8-11:  uint32  width
# Bytes 12-15: uint32  channels
# Bytes 16+:   raw pixel data (h * w * c bytes)
HEADER_SIZE = 16
SHM_SIZE = 8_388_608  # 8MB — fits up to 1920x1080x3 + header
SHM_NAME = "pb_frame"

# --- Message types: Tracking → Display (state_queue) ---
MSG_FRAME_READY = "frame_ready"
MSG_DETECTIONS = "detections"
MSG_SCORE_UPDATE = "score_update"
MSG_LOG = "log"
MSG_BOUNCE = "bounce"
MSG_SERVE = "serve"
MSG_STATUS = "status"
MSG_SOURCE = "source"
MSG_FRAME_POS = "frame_pos"
MSG_RESET = "reset"

# --- Command types: Display → Tracking (cmd_queue) ---
CMD_START = "start"
CMD_STOP = "stop"
CMD_PAUSE = "pause"
CMD_RESUME = "resume"
CMD_REWIND = "rewind"


def write_frame(shm, lock, frame, seq):
    """Write a numpy frame to shared memory with a header."""
    h, w, c = frame.shape
    data_size = h * w * c
    if HEADER_SIZE + data_size > SHM_SIZE:
        return  # frame too large, skip
    header = struct.pack('IIII', seq, h, w, c)
    with lock:
        shm.buf[:HEADER_SIZE] = header
        shm.buf[HEADER_SIZE:HEADER_SIZE + data_size] = frame.tobytes()


def read_frame(shm, lock):
    """Read a numpy frame from shared memory. Returns (frame, seq)."""
    with lock:
        header = bytes(shm.buf[:HEADER_SIZE])
        seq, h, w, c = struct.unpack('IIII', header)
        data_size = h * w * c
        frame_bytes = bytes(shm.buf[HEADER_SIZE:HEADER_SIZE + data_size])
    return np.frombuffer(frame_bytes, dtype=np.uint8).reshape((h, w, c)), seq
