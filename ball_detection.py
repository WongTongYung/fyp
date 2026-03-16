from ultralytics import YOLO

model = YOLO("yolo11m.pt")
    
def image_detection(img):
    results = model(img)
    return results

    for r in results:
        for box in boxes:
            pass
        
