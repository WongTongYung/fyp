import cv2
import threading
import queue

from inference.camera import capture_thread, save_thread, processing_thread
from ultralytics import YOLO
from database import init_db, start_match, end_match
from server import run_server, set_status
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

    # Setup Camera ("Camera")
    cap = cv2.VideoCapture(0) # 0 for webcam
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

    print("Starting streams... (Press 'q' in the 'Processed Stream' window to quit)")
    print("Dashboard: http://localhost:5000")

    # --- Create and Start Threads ---
    flask_t = threading.Thread(target=run_server, daemon=True)
    t1 = threading.Thread(target=capture_thread, args=(cap, save_queue, process_queue, stop_event))
    t2 = threading.Thread(target=save_thread, args=(out, save_queue, stop_event))
    t3 = threading.Thread(target=processing_thread, args=(process_queue, stop_event, model, coord_queue))
    t4 = threading.Thread(target=game_logic_thread, args=(coord_queue, stop_event, match_id))

    flask_t.start()
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