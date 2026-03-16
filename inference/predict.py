from ultralytics import YOLO
import os

model = YOLO("models/yolo11m-custom.pt")

image_folder = "Pickleball Vision.v9i.yolov11/test/images/"


for filename in os.listdir(image_folder):
    if filename.lower().endswith('.jpg'):
        image_path = os.path.join(image_folder, filename)
        model.predict(source = image_path, show = True, save = True, conf = 0.6, line_width = 2, save_crop = True, save_txt = True, show_labels = True, show_conf = True)
    print(f"Processed {filename}")

