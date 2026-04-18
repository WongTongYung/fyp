import queue
import struct
import time
import os
import ctypes
import cv2
from collections import deque

from config import STREAM_FPS, REWIND_BUF_SEC
from core.ball_tracker import BallKalmanTracker
from core.calibration import pixel_to_court
from core.ipc import MSG_FRAME_READY, MSG_FRAME_POS, MSG_DETECTIONS, write_frame

# --- Thread Functions ---


def capture_thread(cap, save_queue, process_queue, stop_event, fps=0,
                   calib_queue=None, static_frame=None, pause_event=None,
                   state_queue=None, shm=None, shm_lock=None):
    """
    Reads frames from the camera and:
      - writes raw frames to shared memory for the display process
      - queues frames for YOLO processing and video saving
    """

    # set high thread priority by calling Windows API directly
    try:
        ctypes.windll.kernel32.SetThreadPriority(-2, 2)  # THREAD_PRIORITY_HIGHEST
    except Exception:
        pass

    # Rate limit for sending frames to the display process
    _last_push_time = 0.0
    _frame_seq = 0

    def _push_frame(frame):
        """Write frame to shared memory and notify display process."""
        nonlocal _last_push_time, _frame_seq
        now = time.time()
        if now - _last_push_time < 1.0 / STREAM_FPS:
            return
        _last_push_time = now
        if shm is not None and state_queue is not None:
            _frame_seq += 1
            write_frame(shm, shm_lock, frame, _frame_seq)
            try:
                state_queue.put_nowait({"type": MSG_FRAME_READY, "seq": _frame_seq})
            except queue.Full:
                pass

    if static_frame is not None:
        while not stop_event.is_set():
            if pause_event and pause_event.is_set():
                time.sleep(0.1)
                continue
            _push_frame(static_frame)
            if not save_queue.full():
                save_queue.put(static_frame)
            if not process_queue.full():
                process_queue.put(static_frame)
            if calib_queue is not None and not calib_queue.full():
                calib_queue.put_nowait(static_frame)
            time.sleep(1.0 / fps if fps > 0 else 1.0 / 30)

        return

    frame_count = 0
    report_fps = fps if fps > 0 else 30
    frame_interval = 1.0 / fps if fps > 0 else 0
    next_frame_time = time.time()
    while not stop_event.is_set():
        if pause_event and pause_event.is_set():
            time.sleep(0.1)
            next_frame_time = time.time()  # reset so no fast-forward catch-up on resume
            continue

        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame, stopping.")
            stop_event.set()
            break

        frame_count += 1
        if frame_count % 30 == 0:
            if state_queue is not None:
                try:
                    state_queue.put_nowait({
                        "type": MSG_FRAME_POS,
                        "frame_pos": frame_count,
                        "fps": report_fps,
                    })
                except queue.Full:
                    pass

        _push_frame(frame)

        try:
            save_queue.put_nowait(frame)
        except queue.Full:
            pass

        try:
            process_queue.put_nowait(frame)
        except queue.Full:
            pass

        if calib_queue is not None:
            try:
                calib_queue.put_nowait(frame)
            except queue.Full:
                pass

        # Throttle to real-time when reading from a video file
        # (cap.read() returns instantly for files, but blocks for live cameras)
        if frame_interval > 0:
            next_frame_time += frame_interval
            sleep_time = next_frame_time - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)



def save_thread(out, save_queue, stop_event, rewind_event=None, fps=30):
    """Thread function to save frames to a file.

    Keeps a rolling buffer of the last ~15 seconds of JPEG-compressed frames.
    When *rewind_event* is set, writes the buffer to a separate rewind clip
    file that the browser can play immediately — the main recording is never
    interrupted.
    """
    buf_max = max(REWIND_BUF_SEC * (fps if fps > 0 else 30), 1)
    frame_buffer = deque(maxlen=buf_max)

    _clip_written = False
    _frame_size = None
    while not stop_event.is_set() or not save_queue.empty():
        # When rewind is triggered, write the buffered frames to a clip
        if rewind_event is not None and rewind_event.is_set():
            if not _clip_written and _frame_size:
                _write_rewind_clip(frame_buffer, fps, _frame_size)
                _clip_written = True
            time.sleep(0.1)
            continue
        _clip_written = False

        try:
            frame = save_queue.get(timeout=1)
            _frame_size = (frame.shape[1], frame.shape[0])
            out.write(frame)
            # Buffer a JPEG-compressed copy for rewind
            _, jpg = cv2.imencode('.jpg', frame)
            frame_buffer.append(jpg)
        except queue.Empty:
            if stop_event.is_set():
                break
            continue


def _write_rewind_clip(frame_buffer, fps, frame_size):
    """Dump JPEG frames to a binary file for MJPEG streaming.

    Format: [uint32 count][uint32 fps] then for each frame [uint32 size][jpeg bytes]
    """
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    clip_path = os.path.join(_root, 'assets', 'rewind', 'rewind_clip.bin')
    count = len(frame_buffer)
    with open(clip_path, 'wb') as f:
        f.write(struct.pack('<II', count, fps))
        for jpg in frame_buffer:
            data = jpg.tobytes()
            f.write(struct.pack('<I', len(data)))
            f.write(data)
    print(f"[Save] Rewind clip written: {count} frames to {clip_path}")


def processing_thread(process_queue, stop_event, model, coord_queue,
                      court_container=None, state_queue=None):
    """
    YOLO inference thread.
    Extracts detection coordinates and sends them to the display process
    via state_queue — the browser canvas handles the overlay.
    """
    fps_counter = 0
    fps_display = 0.0
    fps_timer = time.time()
    _use_track = True   # flips to False if lap is not installed
    tracker = BallKalmanTracker(dt=1.0, process_noise=100.0, measurement_noise=5.0)

    while not stop_event.is_set():
        try:
            frame = process_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        frame_h, frame_w = frame.shape[:2]

        inference_frame = frame

        # Run YOLO — prefer track() for ByteTrack; fall back to predict() if lap missing
        try:
            if _use_track:
                results = model.track(inference_frame, conf=0.4, verbose=False, imgsz=640,
                                      device="cuda", half=True, persist=True,
                                      tracker="bytetrack.yaml")
            else:
                results = model.predict(inference_frame, conf=0.4, verbose=False, imgsz=640,
                                        device="cuda", half=True)
        except Exception as e:
            if _use_track and "lap" in str(e).lower():
                print("[Processing] lap not installed — falling back to predict(). "
                      "Run: pip install lapx  to enable ByteTrack.")
                _use_track = False
            continue

        # Extract detections as JSON-serializable dicts
        detections = []
        frame_h_det, frame_w_det = inference_frame.shape[:2]
        for result in results:
            if result.boxes is None or len(result.boxes) == 0:
                continue
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().tolist()
                conf = box.conf[0].item()

                box_w = (x2 - x1) / frame_w_det
                box_h = (y2 - y1) / frame_h_det
                if box_w > 0.03 or box_h > 0.03:
                    continue

                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

                det = {
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "cx": cx, "cy": cy, "conf": conf,
                }

                if box.id is not None:
                    det["id"] = int(box.id[0].item())

                detections.append(det)

        # Feed the best detection (highest confidence) into the Kalman filter
        if detections:
            best = max(detections, key=lambda d: d["conf"])
            fcx, fcy = tracker.process_detection(best["cx"], best["cy"], best["conf"])
            for det in detections:
                det["source"] = "YOLO"
            if not coord_queue.full():
                coord_queue.put_nowait({
                    "cx": fcx, "cy": fcy, "conf": best["conf"],
                    "predicted": False,
                })

        else:
            pred = tracker.process_miss()
            if pred is not None:
                pcx, pcy = pred
                decay_conf = max(0.1, 0.5 - 0.08 * tracker.miss_count)
                detections.append({
                    "x1": pcx - 8, "y1": pcy - 8,
                    "x2": pcx + 8, "y2": pcy + 8,
                    "cx": pcx, "cy": pcy,
                    "conf": decay_conf,
                    "source": "Kalman",
                })
                if not coord_queue.full():
                    coord_queue.put_nowait({
                        "cx": pcx, "cy": pcy, "conf": decay_conf,
                        "predicted": True,
                    })

        # Court polygon + homography (if available)
        court_pts = None
        H = None
        if court_container is not None:
            with court_container["lock"]:
                poly = court_container["poly"]
                H = court_container.get("H")
            if poly is not None:
                court_pts = poly.tolist()

        # Add real-world court coordinates to each detection
        if H is not None:
            for det in detections:
                cx_cm, cy_cm = pixel_to_court(det["cx"], det["cy"], H)
                det["court_x"] = round(cx_cm, 1)
                det["court_y"] = round(cy_cm, 1)

        # FPS counter
        fps_counter += 1
        elapsed = time.time() - fps_timer
        if elapsed >= 1.0:
            fps_display = fps_counter / elapsed
            fps_counter = 0
            fps_timer = time.time()

        # Send detections to display process via state_queue
        if state_queue is not None:
            try:
                state_queue.put_nowait({
                    "type": MSG_DETECTIONS,
                    "detections": detections,
                    "frame_w": frame_w,
                    "frame_h": frame_h,
                    "court": court_pts,
                    "fps": fps_display,
                })
            except queue.Full:
                pass

