# Pickleball Automated Point Counting Using AI
## User Manual

**Author:** Wong Tong Yung (87100)  
**Programme:** Bachelor of Computer Science with Honours (Network Computing)  
**Institution:** Universiti Malaysia Sarawak (UNIMAS)  
**GitHub:** https://github.com/WongTongYung/fyp

---

## 1. System Requirements

| Requirement | Details |
|---|---|
| Operating System | Windows 10 / Windows 11 |
| Python Version | 3.10 – 3.12 (Python 3.13 not supported) |
| GPU | NVIDIA CUDA GPU (recommended for real-time inference) |
| Camera | USB webcam, DroidCam, iVCam (WiFi), or a video file |
| RAM | Minimum 8 GB recommended |

---

## 2. Installation

### Step 1 — Clone or extract the source code

```bash
git clone https://github.com/WongTongYung/fyp.git
cd fyp
```

Or extract the provided zip file and open the folder.

### Step 2 — Create a virtual environment (recommended)

```bash
py -3.10 -m venv venv
venv\Scripts\activate
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Install PyTorch

**With CUDA GPU acceleration (recommended):**
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

**CPU only (slower, no GPU required):**
```bash
pip install torch torchvision
```

> The `lap` package (required by ByteTrack) is automatically installed by `ultralytics` on first run — no manual step needed.

---

## 3. Running the System

Open a terminal in the project folder with the virtual environment activated.

### Option A — Run with a video file
```bash
python main.py assets/your_video.mp4
```

### Option B — Run with a live camera
```bash
python main.py 0        # default camera (index 0)
python main.py 1        # second camera (index 1)
```

### Option C — Run without pre-selecting a camera
```bash
python main.py
```

Then open a browser and go to:

```
http://127.0.0.1:5000
```

Navigate to **Settings** to select your camera source, then press **Start**.

---

## 4. Court Calibration

Calibration must be done on first run, or after pressing **Calibrate** in the dashboard.

1. A calibration canvas appears in the live video panel
2. Click **6 points** on the court in this exact order:

| Order | Point |
|---|---|
| 1 | Top-Left corner |
| 2 | Top-Right corner |
| 3 | Bottom-Right corner |
| 4 | Bottom-Left corner |
| 5 | Net-Left |
| 6 | Net-Right |

3. Press **Save** — calibration is stored in `data/court.json` and persists across sessions

> Accurate calibration is critical for correct IN/OUT bounce detection.

---

## 5. Using the Dashboard

The web dashboard runs at `http://127.0.0.1:5000` and provides the following panels:

| Panel | Description |
|---|---|
| **Video Feed** | Live stream with ball detection overlay and court view |
| **Scoreboard** | Real-time scores, server indicator, singles/doubles mode |
| **Event Log** | Live bounce (IN/OUT), serve, and side-out events |
| **Live Stats** | Points, side-outs, IN/OUT bounce counts, serve count |
| **Controls** | Start / Stop / Pause / Rewind / Calibrate / Settings |
| **Match History** (`/matches`) | List of all recorded matches with timestamps |
| **Post-Match Analysis** (`/analysis/<id>`) | Bounce heatmap, score timeline, event breakdown |

### Dashboard Controls

| Button | Action |
|---|---|
| Start | Begin detection and scoring |
| Stop | End the current match and save to database |
| Pause | Pause detection (scoring suspended) |
| Rewind | Play back the last 15 seconds of footage |
| Calibrate | Open court calibration mode |
| Settings | Change camera source or game mode |

### Scoring Adjustments

Use the **+** and **−** buttons on the scoreboard to manually correct scores if needed.

---

## 6. Game Modes

| Mode | Description |
|---|---|
| **Singles** | One player per side; one serve per side-out |
| **Doubles** | Two players per side; both players serve before side-out |

Select the mode in **Settings** before starting a match.

---

## 7. Match History and Analysis

- All matches are automatically saved to `data/pickleball.db` (SQLite)
- View past matches at `http://127.0.0.1:5000/matches`
- Click any match to view post-match analysis including bounce heatmap and score timeline

---

## 8. Troubleshooting

| Problem | Solution |
|---|---|
| Camera FPS drops on DroidCam/iVCam | Expected on Windows — `win_perf.py` handles this automatically |
| Ball not detected accurately | Ensure good lighting and re-run court calibration |
| `torch` not found error | Ensure the virtual environment is activated before running |
| Port 5000 already in use | Stop any other Flask app, or change the port in `core/server.py` |
| `lap` install error | Run `pip install lapx` as an alternative |

---

## 9. Project Structure

```
pickleball/
├── main.py                  # Entry point
├── config.py                # Model path and shared config
├── requirements.txt         # Python dependencies
├── core/
│   ├── ball_tracker.py      # Kalman filter tracking
│   ├── calibration.py       # Court calibration & homography
│   ├── database.py          # Match/event/score persistence
│   ├── game_logic.py        # Scoring engine
│   ├── server.py            # Flask server & MJPEG stream
│   └── win_perf.py          # Windows performance optimisations
├── inference/
│   └── camera.py            # Camera capture and YOLO inference
├── models/
│   └── best26m-improved5.pt # Fine-tuned YOLOv11m model
├── dashboard/               # Web UI (HTML, CSS, JS)
└── data/
    ├── pickleball.db        # SQLite match database (auto-generated)
    └── court.json           # Saved court calibration (auto-generated)
```

---

*For source code and latest updates, visit: https://github.com/WongTongYung/fyp*
