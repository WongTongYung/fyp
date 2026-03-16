from vision import image_read
from ball_detection import image_detection
import cv2 as cv
import sys

img_path = "styles/pickleball.jpg"
video_path = 'styles/video.mp4'


def video_display():
    cap = cv.VideoCapture(video_path)
    
    if not cap.isOpened():
        sys.exit(f"Error: Could not open video file: {video_path}")
        exit()    

    while True:
        # Capture frame-by-frame
        ret, frame = cap.read()
        
        # if frame is read correctly ret is True
        if not ret:
            print("Can't receive frame (stream end?). Exiting ...")
            break
        
        # Display the resulting frame
        cv.imshow('frame', frame)
        if cv.waitKey(1) == ord('q'):
            break
    cap.release()
    cv.destroyAllWindows()
    
def main():
    img = cv.imread(img_path)
    
    if img is None:
        sys.exit("Could not read the image.")
        exit()
    
    video_display()
        
    results = image_detection(img)
    print(results)
    
    for r in results:
        boxes = r.boxes  # Get all boxes from this result object
        for box in boxes:
            # Get the coordinates [x_min, y_min, x_max, y_max]
            x1, y1, x2, y2 = box.xyxy[0]  # [0] because it's a tensor
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2) # Convert to integers
            print(f"Box coordinates: ({x1}, {y1}), ({x2}, {y2})")

            # Get the confidence score (how sure is the model?)
            conf = float(box.conf[0])
            print(f"Confidence: {conf:.2f}")
            
            # Get the class ID (what object is this?)
            cls = int(box.cls[0])
            print(f"Class ID: {cls}")
            
            # Get the human-readable name for the class ID
            # 'r.names' is the dictionary you saw in your output
            class_name = r.names[cls] 
            print(f"Class Name: {class_name}")

            # Let's only draw if we're confident and it's the right object
            if class_name == "sports ball" and conf > 0.3:
                print(f"Found: {class_name} with {conf*100:.2f}% confidence.")
                
                # Draw the rectangle on the original image
                # (img, start_point, end_point, color_B_G_R, thickness)
                cv.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                
                # Put the label and confidence score above the box
                label = f'{class_name}: {conf:.2f}'
                cv.putText(img, label, (x1, y1 - 10), cv.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

    img_display = image_read(img)
    cv.imshow("Display window", img_display)
    q = cv.waitKey(0)
    cv.destroyAllWindows()
           
if __name__ == "__main__":
    main()