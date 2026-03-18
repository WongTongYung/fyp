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
    frame_delay = 1.0 / fps if fps > 0 else 1.0 / 30

    if static_frame is not None:
        while not stop_event.is_set():
            if pause_event and pause_event.is_set():
                time.sleep(0.1)
                continue
            if not save_queue.full():
                save_queue.put(static_frame.copy())
            if not process_queue.full():
                process_queue.put(static_frame.copy())
            if calib_queue is not None and not calib_queue.full():
                calib_queue.put_nowait(static_frame.copy())
            time.sleep(frame_delay)
        print("Capture thread stopped.")
        return

    frame_delay = 1.0 / fps if fps > 0 else 0
    frame_count = 0
    report_fps = fps if fps > 0 else 30
    while not stop_event.is_set():
        if pause_event and pause_event.is_set():
            time.sleep(0.1)
            continue

        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame, stopping.")
            stop_event.set()
            break

        frame_count += 1
        if frame_count % 30 == 0:
            set_frame_pos(frame_count, report_fps)

        if not save_queue.full():
            save_queue.put(frame.copy())

        if not process_queue.full():
            process_queue.put(frame.copy())

        if calib_queue is not None and not calib_queue.full():
            calib_queue.put_nowait(frame.copy())

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
    while not stop_event.is_set():
        if not process_queue.empty():
            frame = process_queue.get()
            
            # Run YOLO inference
            results = model.predict(frame, conf=0.3, verbose=False, imgsz=640)
            
            # Extract ball coordinates
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    confidence = box.conf[0].item()
                    # Center point of the ball
                    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                    
                    #print(f"Ball detected at ({cx:.1f}, {cy:.1f}) conf={confidence:.2f}")
                    
                    if not coord_queue.full():
                        coord_queue.put_nowait({"cx": cx, "cy": cy, "conf": confidence})

                
                # Draw detections on frame
                annotated = result.plot()

            out = annotated if results[0].boxes else frame
            if court_container is not None:
                with court_container["lock"]:
                    poly = court_container["poly"]
                if poly is not None:
                    cv2.polylines(out, [poly.astype(np.int32)], isClosed=True, color=(0, 255, 0), thickness=2)
            push_frame(out)
            
    print("Processing thread stopped.")
