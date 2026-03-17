import cv2
import queue

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

def processing_thread(process_queue, stop_event, model, coord_queue):
    while not stop_event.is_set():
        if not process_queue.empty():
            frame = process_queue.get()
            
            # Run YOLO inference
            results = model.predict(frame, conf=0.3, verbose=False)
            
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
            
            cv2.imshow('Processed Stream', annotated if results[0].boxes else frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                stop_event.set()
                break
            
    print("Processing thread stopped.")
