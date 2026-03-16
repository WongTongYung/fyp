import cv2
import threading
import queue
import time

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
    
    # Simulate a slow process (like a heavy neural network)
    # REMOVE THIS IN YOUR REAL APPLICATION
    #time.sleep(0.05) # Simulate 50ms processing time
    
    return processed_frame

# --- 2. Define Thread Functions ---

def capture_thread(cap, save_queue, process_queue, stop_event):
    """
    Thread function to read frames from the camera.
    This corresponds to the "Camera" block.
    """
    print("Starting capture thread...")
    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame, stopping.")
            stop_event.set()
            break
            
        # Put the raw frame into both queues
        # This "splits" the stream from the diagram
        if not save_queue.full():
            save_queue.put(frame.copy()) # "Saves Raw File" stream
            
        if not process_queue.full():
            process_queue.put(frame.copy()) # "Raw video stream"
            
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

def processing_thread(process_queue, stop_event):
    """
    Thread function to process frames.
    This corresponds to "Video processing", "Vision module", etc.
    """
    print("Starting processing thread...")
    while not stop_event.is_set() or not process_queue.empty():
        try:
            # Get a frame from the queue, wait 1 second if empty
            frame = process_queue.get(timeout=1)
            
            # Run your vision logic
            processed_frame = processing_function(frame)
            
            # Display the result (part of your "Scoreboard" or analysis)
            cv2.imshow('Processed Stream', processed_frame)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                stop_event.set()
                break
                
        except queue.Empty:
            if stop_event.is_set():
                break # Exit loop if stop is requested and queue is empty
            continue # Continue waiting if not stopped
            
    print("Processing thread stopped.")

# --- 3. Main Execution ---

if __name__ == "__main__":
    # --- Setup ---
    # Queues to hold frames (buffers)
    # maxsize limits RAM usage
    save_queue = queue.Queue(maxsize=128)
    process_queue = queue.Queue(maxsize=32)
    
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
    out = cv2.VideoWriter('raw_video_output.mp4', fourcc, fps, (frame_width, frame_height))
    if not out.isOpened():
        print("Error: Could not open video writer.")
        cap.release()
        exit()

    print(f"Starting streams... (Press 'q' in the 'Processed Stream' window to quit)")

    # --- Create and Start Threads ---
    t1 = threading.Thread(target=capture_thread, args=(cap, save_queue, process_queue, stop_event))
    t2 = threading.Thread(target=save_thread, args=(out, save_queue, stop_event))
    t3 = threading.Thread(target=processing_thread, args=(process_queue, stop_event))
    
    t1.start()
    t2.start()
    t3.start()
    
    # --- Wait for Threads to Finish ---
    t1.join()
    t2.join()
    t3.join()
    
    # --- Cleanup ---
    print("All threads joined. Cleaning up.")
    cap.release()
    out.release()
    cv2.destroyAllWindows()