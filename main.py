import cv2
import threading
import queue
import sys
import os
import webbrowser
import time

from inference.camera import capture_thread, save_thread, processing_thread
from ultralytics import YOLO
from database import init_db, start_match, end_match
from server import run_server, set_status, set_stop_event, set_pause_event, set_start_callback, set_source, add_log
from game_logic import game_logic_thread
from calibration import get_court, calibration_thread

model = YOLO("models/yolo11m-custom.pt")


def run_pipeline(source):
    """Run the full processing pipeline for a given video/image source."""
    init_db()
    match_id = start_match()
    print(f"Match started (ID: {match_id})")
    add_log(f"Match started (ID: {match_id})")

    # Queues for threads
    save_queue = queue.Queue(maxsize=128)
    process_queue = queue.Queue(maxsize=32)
    coord_queue = queue.Queue(maxsize=64)

    # Events to signal threads to stop or pause
    stop_event = threading.Event()
    pause_event = threading.Event()
    set_stop_event(stop_event)
    set_pause_event(pause_event)

    # Determine source type
    is_file = source != 0
    IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
    is_image = is_file and os.path.splitext(str(source))[1].lower() in IMAGE_EXTS
    set_source(source)

    static_frame = None
    cap = None
    if is_image:
        static_frame = cv2.imread(source)
        if static_frame is None:
            print(f"Error: Could not read image: {source}")
            add_log(f"Error: Could not read image: {source}")
            return
        frame_height, frame_width = static_frame.shape[:2]
        fps = 30
    else:
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            print("Error: Could not open video source.")
            add_log("Error: Could not open video source.")
            return
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(cap.get(cv2.CAP_PROP_FPS))

    # Setup Video Writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter('styles/raw_video_output.mp4', fourcc, fps, (frame_width, frame_height))
    if not out.isOpened():
        print("Error: Could not open video writer.")
        add_log("Error: Could not open video writer.")
        if cap:
            cap.release()
        return

    # Grab first frame for calibration (skip interactive picker)
    if is_image:
        first_frame = static_frame.copy()
    else:
        ret, first_frame = cap.read()
        if not ret:
            print("Error: Could not read first frame.")
            add_log("Error: Could not read first frame.")
            cap.release()
            out.release()
            return
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # reset to beginning

    # Court calibration
    court_poly = get_court(first_frame)
    court_container = {"poly": court_poly, "lock": threading.Lock()}
    if court_poly is None:
        print("[Calibration] No court set — will retry automatically from live frames")
        add_log("No court set — will retry automatically")

    calib_queue = queue.Queue(maxsize=4)

    print("Starting streams...")
    add_log("Starting streams...")

    # --- Create and Start Threads ---
    t1 = threading.Thread(target=capture_thread, args=(cap, save_queue, process_queue, stop_event, fps if is_file else 0, calib_queue, static_frame, pause_event))
    t2 = threading.Thread(target=save_thread, args=(out, save_queue, stop_event))
    t3 = threading.Thread(target=processing_thread, args=(process_queue, stop_event, model, coord_queue, court_container))
    t4 = threading.Thread(target=game_logic_thread, args=(coord_queue, stop_event, match_id, court_container))
    t5 = threading.Thread(target=calibration_thread, args=(calib_queue, court_container, stop_event))

    set_status("live")
    t1.start()
    t2.start()
    t3.start()
    t4.start()
    #t5.start()

    # --- Wait for Threads to Finish ---
    t1.join()
    t2.join()
    t3.join()
    t4.join()
    #t5.join()

    # --- Cleanup ---
    set_status("stopped")
    end_match(match_id)
    print(f"Match ended (ID: {match_id}). Cleaning up.")
    add_log(f"Match ended (ID: {match_id})")
    if cap:
        cap.release()
    out.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    # Register pipeline so dashboard /start route can trigger it
    set_start_callback(run_pipeline)

    # Start Flask server
    flask_t = threading.Thread(target=run_server, daemon=True)
    flask_t.start()
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:5000")

    # If source given via CLI, run pipeline directly
    if len(sys.argv) > 1:
        run_pipeline(sys.argv[1])
    else:
        # Wait for dashboard to trigger start
        print("Dashboard ready at http://127.0.0.1:5000 — use the Start button.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
