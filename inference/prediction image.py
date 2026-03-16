from ultralytics import YOLO

model = YOLO("models/yolo11m-custom.pt")

model.predict(source = "styles/bestball.mp4", show = True, save = True, conf = 0.3, line_width = 2, save_crop = True, save_txt = True, show_labels = True, show_conf = True)

