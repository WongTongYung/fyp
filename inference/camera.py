import cv2
import queue
import time
import numpy as np
from server import push_frame, set_frame_pos

# --- 1. Define Your Processing Function ---
# This function represents your "Video processing" and "Vision module"
def processing_function(frame):
    """
    This is a placeholder for your actual vision logic.
    e.g., object detection, coordinate extraction.
    """
    # Example: Convert to grayscale and apply a blur
    processed_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    processed_frame = cv2.GaussianBlur(processed_frame, (7, 7), 0)
    
    return processed_frame

# --- 2. Define Thread Functions ---

def capture_thread(cap, save_queue, process_queue, stop_event, fps=0, calib_queue=None, static_frame=None, pause_event=None):
    """
    Thread function to read frames from the camera.
    fps: if > 0, sleep between frames to match video speed (for file sources).
         Leave as 0 for webcam — hardware already limits the rate.
    static_frame: if set, loop this single image instead of reading from cap.
    pause_event: when set, the thread idles without reading new frames.
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
    """
    Thread function to save frames to a file.
    This corresponds to "Video storage".
    """
    print("Starting save thread...")
    while not stop_event.is_set() or not save_queue.empty():
        try:
            # Get a frame from the queue, wait 1 second if empty
            frame = save_queue.get(timeout=1) 
            out.write(frame)
        except queue.Empty:
            if stop_event.is_set():
                break # Exit loop if stop is requested and queue is empty
            continue # Continue waiting if not stopped
            
    print("Save thread stopped.")

def processing_thread(process_queue, stop_event, model, coord_queue, court_container=None):
    fps_counter = 0
    fps_display = 0.0
    fps_timer = time.time()

    while not stop_event.is_set():
        try:
            frame = process_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        # Run YOLO inference
        t0 = time.time()
        results = model.predict(frame, conf=0.5, verbose=False, imgsz=640, device="cuda", half=True)
        t1 = time.time()

        # Extract ball coordinates
        for result in results:
            boxes = result.boxes
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                confidence = box.conf[0].item()
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

                if not coord_queue.full():
                    coord_queue.put_nowait({"cx": cx, "cy": cy, "conf": confidence})

            annotated = result.plot()

        t2 = time.time()
        out = annotated if results[0].boxes else frame
        #print(f"[Timing] predict={1000*(t1-t0):.1f}ms  plot+rest={1000*(t2-t1):.1f}ms  total={1000*(t2-t0):.1f}ms")

        if court_container is not None:
            with court_container["lock"]:
                poly = court_container["poly"]
            if poly is not None:
                cv2.polylines(out, [poly.astype(np.int32)], isClosed=True, color=(0, 255, 0), thickness=2)

        # FPS counter
        fps_counter += 1
        elapsed = time.time() - fps_timer
        if elapsed >= 1.0:
            fps_display = fps_counter / elapsed
            fps_counter = 0
            fps_timer = time.time()
        cv2.putText(out, f"FPS: {fps_display:.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

        push_frame(out)

    print("Processing thread stopped.")
