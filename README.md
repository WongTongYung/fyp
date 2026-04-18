<img width="1860" height="971" alt="dashboard" src="https://github.com/user-attachments/assets/7057c8b2-9af2-4319-8a4f-99a8119c8a7e" /># Pickleball Tracking System

A real-time pickleball ball tracking and scoring system using **YOLOv11** computer vision, served through a live web dashboard. Designed for a fixed overhead/side camera setup with automatic court calibration, full scoring logic, and post-match video review.

---

## Demo

> Add a screenshot or screen recording here.
>
> **Images:** Drop a `.png` into the `docs/` folder, then replace the line below:
> ```
> <img width="1860" height="971" alt="dashboard" src="https://github.com/user-attachments/assets/c290e019-ff61-4626-ac8d-3b2271c38b15" />
> ```
>

https://github.com/user-attachments/assets/b89b8c28-d4fb-47b9-9527-6d0dff7da809

---

## Features

- **Real-time ball detection** at 25+ fps using a fine-tuned YOLOv11m model
- **Kalman filter tracking** to smooth detections and bridge occlusion gaps
- **Full pickleball scoring rules** — serve detection, rally tracking, side-out logic, singles & doubles modes
- **Live web dashboard** — MJPEG video stream, scoreboard, bounce log, and court view
- **Interactive court calibration** — click 6 points (4 corners + 2 net points) to define the court
- **IN / OUT bounce detection** using perspective-transformed court coordinates
- **Match history & video rewind** — every match is saved to SQLite and raw video is recorded for playback
- **Two-process architecture** — camera/YOLO runs in one process, Flask dashboard in another, connected via shared memory and queues
- **Windows performance optimisations** — prevents Intel iGPU sleep that causes DroidCam/iVCam FPS drops

---

## System Architecture

<img width="843" height="334" alt="system Architecture Fyp" src="https://github.com/user-attachments/assets/c6dd32eb-3037-4fb6-8d35-623e82473af2" />

---

| Component | Role |
|---|---|
| `main.py` | Entry point — spawns both processes, manages shared memory |
| `core/ipc.py` | IPC protocol — 8 MB shared memory frame buffer + message queues |
| `inference/camera.py` | Camera capture, YOLO inference, Kalman tracking, video saving |
| `core/game_logic.py` | Pickleball scoring engine — rally, serve, bounce, side-out |
| `core/calibration.py` | Court calibration UI, homography transform (pixel → court cm) |
| `core/server.py` | Flask server, MJPEG streaming, command handler |
| `core/database.py` | SQLite match/event/score persistence (WAL mode) |
| `core/ball_tracker.py` | Constant-velocity Kalman filter for ball trajectory |
| `core/win_perf.py` | Windows 11 GPU keep-alive and power throttling disable |
| `dashboard/` | Web UI — scoreboard, live video, event log, calibration modal |

---

## Project Structure

```
pickleball/
├── main.py                     # Entry point
├── config.py                   # Model path and shared config
├── data/
│   ├── pickleball.db           # SQLite match database (auto-generated)
│   └── court.json              # Saved court calibration (auto-generated)
├── core/
│   ├── ball_tracker.py         # Kalman filter
│   ├── calibration.py          # Court calibration & homography
│   ├── database.py             # Match/event/score persistence
│   ├── game_logic.py           # Scoring engine
│   ├── ipc.py                  # IPC constants and shared memory spec
│   ├── server.py               # Flask server & MJPEG stream
│   └── win_perf.py             # Windows performance optimisations
├── inference/
│   ├── camera.py               # Capture, YOLO, save threads
│   └── debug_camera.py         # FPS debugging utility
├── models/
│   └── best26m-improved3.pt    # Active fine-tuned YOLOv11m model
├── dashboard/
│   ├── index.html              # Main dashboard UI
│   ├── css/style.css
│   └── js/main.js
├── assets/
│   └── rewind/                 # Recorded match video output
└── training/                   # Training scripts and datasets
```

---

## Requirements

- **Python** 3.10+
- **OS:** Windows 10/11 (Linux/macOS: `core/win_perf.py` must be skipped)
- **GPU:** NVIDIA CUDA GPU recommended for real-time inference
- **Camera:** USB webcam, DroidCam / iVCam (WiFi), or a video file

Install dependencies:

```bash
pip install ultralytics opencv-python flask torch torchvision numpy pillow
```

> **H.264 video recording (Windows):** Place `openh264-1.8.0-win64.dll` in the project root alongside `main.py`. OpenCV looks for it automatically in the working directory to encode match recordings. Without it, the rewind/recording feature will not work. The file is excluded from git (`.gitignore`) so it must be obtained separately.

---

## Usage

### Run with a video file

```bash
python main.py --source assets/FixedCamera.mp4
```

### Run with a live camera

```bash
python main.py --source 0        # default camera
python main.py --source 1        # second camera
```

### Run dashboard only (no source — start tracking from the UI)

```bash
python main.py
```

Then open **http://127.0.0.1:5000** in your browser and press **Start** in the dashboard.

---

## Court Calibration

On first run, or after pressing **Calibrate** in the dashboard:

1. A calibration canvas appears in the live video panel
2. Click **6 points** in order: Top-Left → Top-Right → Bottom-Right → Bottom-Left → Net-Left → Net-Right
3. Press **Save** — calibration is stored in `court.json` and persists across sessions

The system uses a perspective homography transform to convert pixel coordinates to real court distances (cm), enabling accurate IN/OUT detection.

---

## Model

| Model file | Base | Training |
|---|---|---|
| `best26m-improved3.pt` | YOLOv11m | Fine-tuned on Pickleball Vision dataset |

**Dataset:** [Roboflow — Pickleball Vision](https://universe.roboflow.com/liberin-technologies/pickleball-vision/dataset/9)

| Split | Images |
|---|---|
| Train | 4,483 |
| Valid | 737 |
| Test | 170 |

Training: 100 epochs, 640×640 input, batch size 16, early stopping (25 epochs patience).

To retrain:

```bash
python training/train.py
```

---

## Dashboard

The web dashboard runs at **http://127.0.0.1:5000** and provides:

| Panel | Contents |
|---|---|
| Video feed | Live MJPEG stream with ball detection overlay and court view |
| Scoreboard | Real-time scores, server indicator, singles/doubles mode |
| Event log | Live bounce (IN/OUT), serve, and side-out events |
| Live stats | Points, side-outs, IN/OUT bounce counts, serve count |
| Controls | Start / Stop / Pause / Rewind / Calibrate / Settings |

---

## Scoring Logic

The game logic engine in `core/game_logic.py` implements official pickleball rules:

- **Rally detection** — tracks ball bounces to determine when a rally ends
- **Serve detection** — velocity threshold (120 px/frame) to identify serve shots
- **IN / OUT** — point-in-polygon test against the calibrated court polygon
- **Side-out** — server loses the rally → service passes to opponent
- **Doubles** — server number (1 or 2) tracked; both players serve before side-out
- **Manual override** — +/− buttons on dashboard for score correction

---

## Performance Notes

The system uses a **2-process design** to avoid Python's GIL blocking YOLO inference during video capture. Video frames are shared between processes via 8 MB POSIX shared memory — fast enough for 1080p at 30fps with no serialisation overhead.

On Windows 11 with DroidCam / iVCam, the Intel iGPU hardware decoder sleeps aggressively under low GPU load, causing FPS drops from 60 → 17. `core/win_perf.py` addresses this by:
- Keeping a 1×1 pixel OpenGL window rendering at 10fps to hold the iGPU awake
- Disabling EcoQoS power throttling via Win32 API
- Raising process priority and setting the Windows timer resolution to 1ms

---

## Roadmap

- [x] Dataset collection and labelling
- [x] YOLOv11m model training (multiple iterations)
- [x] Multi-threaded camera capture pipeline
- [x] Real-time YOLO ball detection
- [x] Kalman filter ball tracking
- [x] Court calibration with perspective homography
- [x] IN / OUT bounce detection
- [x] Serve detection
- [x] Full pickleball scoring engine (singles & doubles)
- [x] Live web dashboard (MJPEG + scoreboard + event log)
- [x] SQLite match persistence
- [x] Match video recording & rewind
- [x] Match history page
- [x] Windows GPU performance fixes

---

## Author

Final Year Project — Tong Yung  
Bachelor of Computer Science, 2026
