"""
Debug script: shows raw camera feed with actual FPS counter.
Run: python debug_camera.py [camera_index]
"""
import cv2
import time
import sys

CAMERA_INDEX = int(sys.argv[1]) if len(sys.argv) > 1 else 2

cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_MSMF)
if not cap.isOpened():
    print(f"Could not open camera {CAMERA_INDEX}")
    sys.exit(1)

reported_fps = cap.get(cv2.CAP_PROP_FPS)
w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"Camera {CAMERA_INDEX}: {w}x{h} @ {reported_fps:.1f}fps (reported)")

frame_count = 0
fps_display = 0.0
t_start = time.time()

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to grab frame.")
        break

    frame_count += 1
    elapsed = time.time() - t_start
    if elapsed >= 1.0:
        fps_display = frame_count / elapsed
        frame_count = 0
        t_start = time.time()

    cv2.putText(frame, f"Actual FPS: {fps_display:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    cv2.putText(frame, f"Reported: {reported_fps:.1f}", (10, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)

    cv2.imshow(f"Camera {CAMERA_INDEX} - Raw Feed", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
