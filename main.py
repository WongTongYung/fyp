import cv2
import threading
import queue
import multiprocessing
import sys
import os
import webbrowser
import time
import atexit
import torch

from multiprocessing.shared_memory import SharedMemory
from inference.camera import capture_thread, save_thread, processing_thread
from ultralytics import YOLO
from database import init_db, start_match, end_match
from game_logic import game_logic_thread
from calibration import get_court, compute_homography
from config import BALL_MODEL_PATH
from ipc import (SHM_SIZE, SHM_NAME,
                 MSG_STATUS, MSG_SOURCE, MSG_LOG,
                 CMD_START, CMD_STOP, CMD_PAUSE, CMD_RESUME, CMD_REWIND)
from win_perf import win32_perf_setup, keep_igpu_alive

# Limit PyTorch CPU threads so iVCam decoder gets more CPU headroom
torch.set_num_threads(2)
torch.backends.cudnn.benchmark = True

win32_perf_setup()


def _send(state_queue, msg):
    """Send a message to the display process (non-blocking)."""
    try:
        state_queue.put_nowait(msg)
    except queue.Full:
        pass


def run_display_process(cmd_queue, state_queue, shm_name, shm_lock):
    """Entry point for Process 2 (Display). Runs Flask server."""
    win32_perf_setup()  # Also fix timer/throttling in the display process
    from server import init_display_process, run_server
    init_display_process(cmd_queue, state_queue, shm_name, shm_lock)
    run_server()


def cmd_listener_thread(cmd_queue, stop_event, pause_event, rewind_event=None):
    """Translates IPC commands from display process into local threading.Events."""
    while not stop_event.is_set():
        try:
            cmd = cmd_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        cmd_type = cmd.get("type")
        if cmd_type == CMD_STOP:
            pause_event.clear()
            stop_event.set()
        elif cmd_type == CMD_PAUSE:
            pause_event.set()
        elif cmd_type == CMD_RESUME:
            pause_event.clear()
            if rewind_event:
                rewind_event.clear()
        elif cmd_type == CMD_REWIND:
            pause_event.set()
            if rewind_event:
                rewind_event.set()


def run_pipeline(source, state_queue, shm, shm_lock, cmd_queue, model, config=None):
    """Full pipeline: capture → raw MJPEG + YOLO detections via IPC."""
    init_db()
    match_id = start_match()
    print(f"Match started (ID: {match_id})")
    _send(state_queue, {"type": MSG_LOG, "message": f"Match started (ID: {match_id})"})

    # Queues for threads
    save_queue = queue.Queue(maxsize=128)
    process_queue = queue.Queue(maxsize=4)
    coord_queue = queue.Queue(maxsize=64)

    # Events to signal threads to stop, pause, or flush video for rewind
    stop_event = threading.Event()
    pause_event = threading.Event()
    rewind_event = threading.Event()

    # Send source to display process
    _send(state_queue, {"type": MSG_SOURCE, "source": source})

    # Determine source type
    is_file = source != 0
    IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
    is_image = is_file and os.path.splitext(str(source))[1].lower() in IMAGE_EXTS

    static_frame = None
    cap = None
    if is_image:
        static_frame = cv2.imread(source)
        if static_frame is None:
            print(f"Error: Could not read image: {source}")
            _send(state_queue, {"type": MSG_LOG, "message": f"Error: Could not read image: {source}"})
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
                        _send(state_queue, {"type": MSG_LOG, "message": f"Camera {i} ({backend_name}): {w}x{h} @ {f}fps"})
                    else:
                        pass
                    test_cap.release()

        # Try multiple backends
        cap = None
        if isinstance(source, int):
            for backend_name, backend in [("MSMF", cv2.CAP_MSMF), ("DSHOW", cv2.CAP_DSHOW), ("AUTO", cv2.CAP_ANY)]:
                cap = cv2.VideoCapture(source, backend)
                if cap.isOpened():
                    print(f"[Camera] Opened camera {source} with {backend_name}")
                    _send(state_queue, {"type": MSG_LOG, "message": f"Opened camera {source} with {backend_name}"})
                    break
                cap.release()
        else:
            cap = cv2.VideoCapture(source)
        if not cap or not cap.isOpened():
            print("Error: Could not open video source.")
            _send(state_queue, {"type": MSG_LOG, "message": "Error: Could not open video source."})
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        if fps == 0:
            fps = 30
            print(f"[Camera] FPS not reported, defaulting to {fps}")
        print(f"[Camera] Resolution: {frame_width}x{frame_height}, FPS: {fps}")

    # Setup Video Writer (H.264 via OpenH264 — browser-playable after match ends)
    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    out = cv2.VideoWriter('styles/raw_video_output.mp4', fourcc, fps, (frame_width, frame_height))
    if not out.isOpened():
        print("Error: Could not open video writer.")
        _send(state_queue, {"type": MSG_LOG, "message": "Error: Could not open video writer."})
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
            _send(state_queue, {"type": MSG_LOG, "message": "Error: Could not read first frame."})
            cap.release()
            out.release()
            return
        if is_file:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    # Court calibration
    calib_cap = cap if is_file else None
    court_result = get_court(first_frame, cap=calib_cap, start_pos=0)
    if is_file and cap is not None:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    if court_result is not None:
        court_poly, net_line = court_result
    else:
        court_poly, net_line = None, None
    H = compute_homography(court_poly, net=net_line) if court_poly is not None else None
    court_container = {"poly": court_poly, "net": net_line, "H": H, "lock": threading.Lock()}
    if court_poly is None:
        print("[Calibration] No court set — will retry automatically from live frames")
        _send(state_queue, {"type": MSG_LOG, "message": "No court set — will retry automatically"})

    calib_queue = queue.Queue(maxsize=4)

    print("Starting streams...")
    _send(state_queue, {"type": MSG_LOG, "message": "Starting streams..."})

    # Use setup config from display process, or empty dict
    setup_config = config or {}

    # --- Create and Start Threads ---
    t1 = threading.Thread(target=capture_thread, args=(
        cap, save_queue, process_queue, stop_event,
        fps if is_file else 0, calib_queue, static_frame, pause_event,
        state_queue, shm, shm_lock,
    ))
    t2 = threading.Thread(target=save_thread, args=(out, save_queue, stop_event, rewind_event, fps))
    t3 = threading.Thread(target=processing_thread, args=(
        process_queue, stop_event, model, coord_queue, court_container,
        state_queue,
    ))
    t4 = threading.Thread(target=game_logic_thread, args=(
        coord_queue, stop_event, match_id, court_container, pause_event,
        state_queue, setup_config,
    ))
    t_cmd = threading.Thread(target=cmd_listener_thread, args=(
        cmd_queue, stop_event, pause_event, rewind_event,
    ), daemon=True)

    _send(state_queue, {"type": MSG_STATUS, "status": "live"})
    t1.start()
    t2.start()
    t3.start()
    t4.start()
    t_cmd.start()

    # Wait for pipeline to finish
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
    _send(state_queue, {"type": MSG_STATUS, "status": "stopped"})
    end_match(match_id)
    print(f"Match ended (ID: {match_id}). Cleaning up.")
    _send(state_queue, {"type": MSG_LOG, "message": f"Match ended (ID: {match_id})"})
    if cap:
        cap.release()
    out.release()
    cv2.destroyAllWindows()


def run_tracking_loop(cmd_queue, state_queue, shm, shm_lock, model):
    """Main loop in the tracking process. Waits for commands, runs pipelines."""
    while True:
        try:
            cmd = cmd_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        except KeyboardInterrupt:
            break

        if cmd.get("type") == CMD_START:
            source = cmd.get("source", 0)
            config = cmd.get("config", {})
            run_pipeline(source, state_queue, shm, shm_lock, cmd_queue, model, config)


if __name__ == "__main__":
    # Keep Intel iGPU active so iVCam doesn't throttle when no window is visible
    _igpu_thread = threading.Thread(target=keep_igpu_alive, daemon=True)
    _igpu_thread.start()

    # --- Create IPC resources ---
    # Clean up any stale shared memory from a previous crash
    try:
        stale = SharedMemory(name=SHM_NAME, create=False)
        stale.close()
        stale.unlink()
    except FileNotFoundError:
        pass

    shm = SharedMemory(name=SHM_NAME, create=True, size=SHM_SIZE)
    shm_lock = multiprocessing.Lock()
    cmd_queue = multiprocessing.Queue()
    state_queue = multiprocessing.Queue(maxsize=512)

    def cleanup():
        try:
            shm.close()
            shm.unlink()
        except Exception:
            pass

    atexit.register(cleanup)

    # --- Load YOLO model (only in tracking process) ---
    model = YOLO(BALL_MODEL_PATH)
    model.to("cuda")

    # --- Start Display Process (Process 2) ---
    display_proc = multiprocessing.Process(
        target=run_display_process,
        args=(cmd_queue, state_queue, SHM_NAME, shm_lock),
        daemon=True,
    )
    display_proc.start()

    time.sleep(1)
    webbrowser.open("http://127.0.0.1:5000")

    # --- Tracking Process (Process 1 = this process) ---
    if len(sys.argv) > 1:
        src = sys.argv[1]
        if src.isdigit():
            src = int(src)
        run_pipeline(src, state_queue, shm, shm_lock, cmd_queue, model)
    else:
        print("Dashboard ready at http://127.0.0.1:5000 — use the Start button.")
        try:
            run_tracking_loop(cmd_queue, state_queue, shm, shm_lock, model)
        except KeyboardInterrupt:
            print("\nShutting down...")
            _send(state_queue, {"type": MSG_STATUS, "status": "shutdown"})
            time.sleep(1)
