import cv2
import threading
import queue
import sys
import os
import webbrowser
import time
import torch

from inference.camera import capture_thread, save_thread, processing_thread
from ultralytics import YOLO
from database import init_db, start_match, end_match
from server import run_server, set_status, set_stop_event, set_pause_event, set_start_callback, set_source, add_log
from game_logic import game_logic_thread
from calibration import get_court

# Limit PyTorch CPU threads so iVCam decoder gets more CPU headroom
torch.set_num_threads(2)
torch.backends.cudnn.benchmark = True

model = YOLO("models/yolo11m-custom.pt")
#model = YOLO("models/yolo11n.pt")
model.to("cuda")


def run_pipeline(source):
    """Full pipeline: capture → raw MJPEG + YOLO detections via SSE."""
    init_db()
    match_id = start_match()
    print(f"Match started (ID: {match_id})")
    add_log(f"Match started (ID: {match_id})")

    # Queues for threads
    save_queue = queue.Queue(maxsize=128)
    process_queue = queue.Queue(maxsize=4)
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
        # Scan available cameras when using camera index
        if isinstance(source, int):
            print("[Camera] Scanning available cameras...")
            for backend_name, backend in [("MSMF", cv2.CAP_MSMF), ("DSHOW", cv2.CAP_DSHOW)]:
                for i in range(5):
                    test_cap = cv2.VideoCapture(i, backend)
                    if test_cap.isOpened():
                        w = int(test_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        h = int(test_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        f = test_cap.get(cv2.CAP_PROP_FPS)
                        print(f"  [Camera {i}] ({backend_name}) Available - {w}x{h} @ {f}fps")
                        add_log(f"Camera {i} ({backend_name}): {w}x{h} @ {f}fps")
                    else:
                        print(f"  [Camera {i}] ({backend_name}) Not available")
                    test_cap.release()

        # Try multiple backends: MSMF (default Windows), then DSHOW, then auto
        cap = None
        if isinstance(source, int):
            for backend_name, backend in [("MSMF", cv2.CAP_MSMF), ("DSHOW", cv2.CAP_DSHOW), ("AUTO", cv2.CAP_ANY)]:
                cap = cv2.VideoCapture(source, backend)
                if cap.isOpened():
                    print(f"[Camera] Opened camera {source} with {backend_name}")
                    add_log(f"Opened camera {source} with {backend_name}")
                    break
                cap.release()
        else:
            cap = cv2.VideoCapture(source)
        if not cap or not cap.isOpened():
            print("Error: Could not open video source.")
            add_log("Error: Could not open video source.")
            return
        # Request 1080p — camera will use closest supported resolution
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        if fps == 0:
            fps = 30
            print(f"[Camera] FPS not reported, defaulting to {fps}")
        print(f"[Camera] Resolution: {frame_width}x{frame_height}, FPS: {fps}")

    # Setup Video Writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter('styles/raw_video_output.mp4', fourcc, fps, (frame_width, frame_height))
    if not out.isOpened():
        print("Error: Could not open video writer.")
        add_log("Error: Could not open video writer.")
        if cap:
            cap.release()
        return

    # Grab first frame for calibration
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
        if is_file:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    # Court calibration — pass cap so manual mode can navigate ±30 frames
    calib_cap   = cap if is_file else None
    court_result = get_court(first_frame, cap=calib_cap, start_pos=0)
    # Ensure cap is back at frame 0 for the capture thread
    if is_file and cap is not None:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    if court_result is not None:
        court_poly, net_line = court_result
    else:
        court_poly, net_line = None, None
    court_container = {"poly": court_poly, "net": net_line, "lock": threading.Lock()}
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

    set_status("live")
    t1.start()
    t2.start()
    t3.start()
    t4.start()

    # buffer the frame for 500ms so can exit gracefully
    try:
        while t1.is_alive() or t3.is_alive():
            t1.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\nCtrl+C received, stopping...")
        stop_event.set()
        
    t1.join()
    t2.join()
    t3.join()
    t4.join()

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
    set_start_callback(run_pipeline)

    flask_t = threading.Thread(target=run_server, daemon=True)
    flask_t.start()
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:5000")

    if len(sys.argv) > 1:
        src = sys.argv[1]
        if src.isdigit():
            src = int(src)
        run_pipeline(src)
    else:
        print("Dashboard ready at http://127.0.0.1:5000 — use the Start button.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
