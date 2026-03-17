import cv2
import threading
import queue
import sys
import webbrowser
import time

from inference.camera import capture_thread, save_thread, processing_thread
from ultralytics import YOLO
from database import init_db, start_match, end_match
from server import run_server, set_status, set_stop_event
from game_logic import game_logic_thread

model = YOLO("models/yolo11m-custom.pt")



if __name__ == "__main__":
    init_db()
    match_id = start_match()
    print(f"Match started (ID: {match_id})")
    # --- Setup ---
    # Queues to hold frames (buffers)
    # maxsize limits RAM usage
    save_queue = queue.Queue(maxsize=128)
    process_queue = queue.Queue(maxsize=32)
    coord_queue = queue.Queue(maxsize=64)
    
    # Event to signal threads to stop
    stop_event = threading.Event()
    set_stop_event(stop_event)

    # Setup Camera — pass a video file path as argument to simulate, e.g.:
    #   python main.py styles/bestball.mp4
    source = sys.argv[1] if len(sys.argv) > 1 else 0
    is_file = source != 0
    
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print("Error: Could not open video source.")
        exit()

    # Get video properties for the writer
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    
    # Setup Video Writer ("Video storage")
    # Using 'XVID' codec. Use 'mp4v' for .mp4 files.
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter('styles/raw_video_output.mp4', fourcc, fps, (frame_width, frame_height))
    if not out.isOpened():
        print("Error: Could not open video writer.")
        cap.release()
        exit()

    print("Starting streams... (Press Ctrl+C or use the Stop button on the dashboard to quit)")

    # --- Create and Start Threads ---
    flask_t = threading.Thread(target=run_server, daemon=True)
    t1 = threading.Thread(target=capture_thread, args=(cap, save_queue, process_queue, stop_event, fps if is_file else 0))
    t2 = threading.Thread(target=save_thread, args=(out, save_queue, stop_event))
    t3 = threading.Thread(target=processing_thread, args=(process_queue, stop_event, model, coord_queue))
    t4 = threading.Thread(target=game_logic_thread, args=(coord_queue, stop_event, match_id))

    flask_t.start()
    time.sleep(1)  # wait for Flask to start before opening browser
    webbrowser.open("http://127.0.0.1:5000")
    set_status("live")
    t1.start()
    t2.start()
    t3.start()
    t4.start()
    
    # --- Wait for Threads to Finish ---
    t1.join()
    t2.join()
    t3.join()
    t4.join()
    
    # --- Cleanup ---
    set_status("stopped")
    end_match(match_id)
    print(f"Match ended (ID: {match_id}). Cleaning up.")
    cap.release()
    out.release()
    cv2.destroyAllWindows()