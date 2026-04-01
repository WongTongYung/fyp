import queue
import time
from server import push_frame, set_frame_pos, push_detections

# --- Thread Functions ---

def capture_thread(cap, save_queue, process_queue, stop_event, fps=0, calib_queue=None, static_frame=None, pause_event=None):
    """
    Reads frames from the camera and:
      - pushes raw frames to the MJPEG stream (push_frame)
      - queues frames for YOLO processing and video saving
    """
    print("Starting capture thread...")
    # Boost capture thread priority so iVCam gets served faster
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadPriority(-2, 2)  # THREAD_PRIORITY_HIGHEST
    except Exception:
        pass
    frame_delay = 1.0 / fps if fps > 0 else 1.0 / 30

    if static_frame is not None:
        while not stop_event.is_set():
            if pause_event and pause_event.is_set():
                time.sleep(0.1)
                continue
            push_frame(static_frame)
            if not save_queue.full():
                save_queue.put(static_frame)
            if not process_queue.full():
                process_queue.put(static_frame)
            if calib_queue is not None and not calib_queue.full():
                calib_queue.put_nowait(static_frame)
            time.sleep(frame_delay)
        print("Capture thread stopped.")
        return

    frame_delay = 1.0 / fps if fps > 0 else 0
    frame_count = 0
    report_fps = fps if fps > 0 else 30
    cap_fps_counter = 0
    cap_fps_timer = time.time()
    while not stop_event.is_set():
        if pause_event and pause_event.is_set():
            time.sleep(0.1)
            continue

        ret, frame = cap.read()
        cap_fps_counter += 1
        if time.time() - cap_fps_timer >= 2.0:
            print(f"[Capture] cap.read() FPS: {cap_fps_counter / (time.time() - cap_fps_timer):.1f}")
            cap_fps_counter = 0
            cap_fps_timer = time.time()
        if not ret:
            print("Failed to grab frame, stopping.")
            stop_event.set()
            break

        frame_count += 1
        if frame_count % 30 == 0:
            set_frame_pos(frame_count, report_fps)

        push_frame(frame)  # raw frame → MJPEG stream

        if not save_queue.full():
            save_queue.put(frame)

        if not process_queue.full():
            process_queue.put(frame)

        if calib_queue is not None and not calib_queue.full():
            calib_queue.put_nowait(frame)

        if frame_delay:
            time.sleep(frame_delay)

    print("Capture thread stopped.")

def save_thread(out, save_queue, stop_event):
    """Thread function to save frames to a file."""
    print("Starting save thread...")
    while not stop_event.is_set() or not save_queue.empty():
        try:
            frame = save_queue.get(timeout=1)
            out.write(frame)
        except queue.Empty:
            if stop_event.is_set():
                break
            continue
    print("Save thread stopped.")

def processing_thread(process_queue, stop_event, model, coord_queue, court_container=None):
    """
    YOLO inference thread.
    Extracts detection coordinates and pushes them via SSE (push_detections)
    instead of drawing on the frame — the browser canvas handles the overlay.
    """
    print("Starting processing thread...")
    fps_counter = 0
    fps_display = 0.0
    fps_timer = time.time()
    _use_track = True   # flips to False if lap is not installed

    while not stop_event.is_set():
        try:
            frame = process_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        frame_h, frame_w = frame.shape[:2]

        # Run YOLO — prefer track() for ByteTrack; fall back to predict() if lap missing
        try:
            if _use_track:
                results = model.track(frame, conf=0.3, verbose=False, imgsz=640,
                                      device="cuda", half=True, persist=True,
                                      tracker="bytetrack.yaml")
            else:
                results = model.predict(frame, conf=0.3, verbose=False, imgsz=640,
                                        device="cuda", half=True)
        except Exception as e:
            if _use_track and "lap" in str(e).lower():
                print("[Processing] lap not installed — falling back to predict(). "
                      "Run: pip install lapx  to enable ByteTrack.")
                _use_track = False
            continue

        # Extract detections as JSON-serializable dicts
        detections = []
        for result in results:
            if result.boxes is None or len(result.boxes) == 0:
                continue
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().tolist()
                conf = box.conf[0].item()
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

                det = {
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "cx": cx, "cy": cy, "conf": conf,
                }

                # Track ID (assigned by ByteTrack, persists across frames)
                if box.id is not None:
                    det["id"] = int(box.id[0].item())

                detections.append(det)

                if not coord_queue.full():
                    coord_queue.put_nowait({"cx": cx, "cy": cy, "conf": conf})

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
            from calibration import pixel_to_court
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

        # Push coordinates to browser via SSE — no frame drawing needed
        push_detections(detections, frame_w, frame_h, court_pts, fps_display)

    print("Processing thread stopped.")
