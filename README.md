# Pickleball Ball Detection & Tracking System

An automated pickleball tracking system using computer vision (YOLOv11) to detect the ball in real-time from a live camera feed, with a web dashboard for score display and post-match analysis.

## System Architecture

![System Architecture](docs/architecture.png)

The system consists of:
- **Camera module** — captures raw video stream and saves it to storage simultaneously
- **Vision module** — runs YOLOv11 object detection to extract ball coordinates from each frame
- **Game logic engine** — interprets ball coordinates to track game events and update scores
- **Dashboard** — displays live scores and post-match analysis via a web interface
- **Database** — stores event logs for post-match review and video rewind

## Project Structure

```
code new/
├── training/
│   ├── train.py                        # Model training script
│   ├── custom_dataset.yaml             # Dataset configuration
│   └── Pickleball Vision.v9i.yolov11/ # Labelled training dataset
├── inference/
│   ├── camera.py                       # Live camera capture + processing pipeline
│   ├── predict.py                      # Batch image prediction
│   └── prediction image.py            # Single video file prediction
├── models/
│   ├── yolo11m.pt                      # Base YOLOv11 model (pre-trained)
│   └── yolo11m-custom.pt              # Fine-tuned model (trained on pickleball dataset)
├── dashboard/
│   ├── index.html                      # Main dashboard UI
│   ├── css/style.css
│   └── js/main.js
├── styles/                             # Test videos and images
└── runs/                               # Training output and prediction results
```

## Requirements

- Python 3.10+
- [Ultralytics YOLO](https://github.com/ultralytics/ultralytics)
- OpenCV (`opencv-python`)
- CUDA-capable GPU (recommended for training)

Install dependencies:

```bash
pip install ultralytics opencv-python
```

## Usage

### Train the model

```bash
python training/train.py
```

### Run live detection (camera)

```bash
python inference/camera.py
```

### Run detection on a video file

```bash
python inference/prediction\ image.py
```

### Run batch prediction on images

```bash
python inference/predict.py
```

## Dataset

| Split | Images |
|-------|--------|
| Train | 4,483  |
| Valid | 737    |
| Test  | 170    |

- **Source:** [Roboflow — Pickleball Vision v9](https://universe.roboflow.com/liberin-technologies/pickleball-vision/dataset/9)
- **Classes:** `ball` (1 class)
- **Format:** YOLOv11

## Model

| Model | Base | Task |
|-------|------|------|
| `yolo11m-custom.pt` | YOLOv11m | Ball detection (fine-tuned) |

Training configuration: 100 epochs, image size 640×640, batch size 16, early stopping at 25 epochs patience.

## Results

> Training metrics and graphs will be added after final model training is complete.

## Roadmap

- [x] Dataset collection and labelling
- [x] Model training pipeline
- [x] Camera capture with threaded pipeline
- [ ] YOLO integration into live camera feed
- [ ] Game logic engine (scoring)
- [ ] Dashboard — live scoreboard
- [ ] Database — event logging
- [ ] Post-match analysis

## Author

Final Year Project — [Your Name]
[Your University], [Year]
