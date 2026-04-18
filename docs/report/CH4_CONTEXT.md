# Chapter 4 Writing Context (Handoff Document)

## How to use this file in a new Claude chat

Open a new chat and paste:

> "I'm continuing work on my Pickleball FYP Chapter 4. Please read `docs/report/CH4_CONTEXT.md` for full context, then help me draft Section [X.X.X]."

Claude will read this file, understand the project state, and continue seamlessly.

---

## Project Overview

- **Title:** Pickleball Automated Point Counting Using AI
- **Author:** Wong Tong Yung (UNIMAS FCSIT, Bachelor of Computer Science Network Computing, 2025/2026)
- **Supervisor:** (name from FYP1 if needed)
- **Phase:** FYP2 — Chapter 4 writing in progress
- **Working directory:** `c:\Users\user\Desktop\sem8\fyp\pickleball`
- **Primary output file:** `docs/report/chapter4.docx`

## Thesis Structure (6-chapter, split — confirmed with supervisor via WhatsApp references)

```
Ch 1: Introduction         (FYP1 — submitted)
Ch 2: Literature Review    (FYP1 — submitted)
Ch 3: Methodology          (FYP1 — submitted)
Ch 4: Implementation       ← CURRENT FOCUS — 25-33 pages target
Ch 5: Testing              ← after Ch 4
Ch 6: Conclusion & Future Works
```

Reference model: `FYP 2 Final Report.pdf` (189 pages, 6-chapter LPG IoT FYP by Muhammad Azri Hafiz)

## Chapter 4 Full Structure

```
4.1  Introduction                                  [DRAFTED]
4.2  Object Detection Module
     4.2.1 Data Collection                         [DRAFTED]
     4.2.2 Data Augmentation                       [DRAFTED]
     4.2.3 Model Training and Fine-tuning          [DRAFTED]
4.3  Backend System
     4.3.1 Two-Process Architecture                [TODO]
     4.3.2 Ball Tracker (Kalman Filter)            [TODO]
     4.3.3 Court Calibration (Homography)          [TODO]
     4.3.4 Game Logic Engine                       [TODO]
     4.3.5 Database                                [TODO]
4.4  Web Dashboard
     4.4.1 Live Scoreboard and Video Stream        [TODO]
     4.4.2 Match History                           [TODO]
     4.4.3 Post-Match Analysis                     [TODO]
4.5  Summary                                       [TODO]
```

## Key Facts (verified against code and training runs)

### Dataset
- **Total images:** 382
- **Split:** 268 train / 76 valid / 38 test (70/20/10)
- **Sources:** (1) local match footage via DroidCam on rear fence, (2) YouTube tournament footage, (3) Roboflow Universe public datasets
- **Classes:** 1 (`ball`)
- **Format:** YOLOv11 (Ultralytics)

### Recording
- **Device:** Smartphone running DroidCam (streams camera to laptop)
- **Resolution:** 1920×1080
- **FPS:** 30 (NOT 60 — confirmed from `extract_frames.py` output)
- **Duration of self-recorded clip:** ~2.5 minutes (154.4 seconds)
- **Frame extraction:** every 60th frame (yields ~77 candidates, culled to 38 labelled)

### Camera Setup (matches Ch 3 Figure 3.3)
- Fixed rear-centre position on court fence
- Elevated approximately 1.5 metres
- Slight upward angle to capture full court

### Final Model
- **File:** `models/best26m-improved4.pt` (copied from `runs/detect/yolo26m-p2-improved4-latest/weights/best.pt`)
- **Architecture:** YOLO26m-P2 (YOLOv11 medium + P2 small-object detection head)
- **Config:** `config.py` line 6 — `BALL_MODEL_PATH = "models/best26m-improved4.pt"`
- **Performance:** mAP50 = 0.901, mAP50-95 = 0.470, P = 0.877, R = 0.833
- **Training iterations:**
  | # | Model | Dataset | mAP50 | mAP50-95 |
  |---|---|---|---|---|
  | 1 | yolo11m-baseline | 344 | 0.849 | 0.396 |
  | 2 | yolo26m-p2-improved2 | 344 | 0.806 | 0.331 |
  | 3 | yolo26m-p2-improved3 | 344 | 0.842 | 0.408 |
  | 4 | **yolo26m-p2-improved4-latest** | **382** | **0.901** | **0.470** |

### Training Hyperparameters (from `training/train.py`)
- Image size 640, batch 4, epochs 100, patience 25, lr0 0.005
- Augmentation: `fliplr=0.5`, `degrees=0.0`, `mosaic=1.0`, `copy_paste=0.3`, `hsv_v=0.4`

## Writing Style Rules (learned from user feedback)

### DO
- Use human voice — simple, direct, not AI-sounding
- Mix short sentences with longer ones
- Use UK spelling: *realisation, generalisation, analyse, colour*
- Justify design decisions honestly (*"This was chosen because..."*)
- Match the user's FYP1 prose tone — simple, direct, not over-formal

### DON'T
- Over-use hedging adverbs (*significantly, substantially, effectively*)
- Use nominalisations when verbs work (*"was annotated"* > *"the annotation workflow was carried out"*)
- Write empty qualifiers (*"complementary sources"*, *"target deployment environment"*)
- Use tutorial-style explanations ("Roboflow is a web-based platform...")
- Put full source code — use snippets 5–10 lines max, label as Listing 4.x
- Narrate code line-by-line — describe what it DOES and WHY

## Figures Referenced in Completed Sections

| Figure | Section | Description | Source |
|---|---|---|---|
| 4.1 | 4.2.1 | Roboflow annotation screenshot | User to capture manually |
| 4.2–4.5 | 4.2.3 | Training curves, PR curve, confusion matrix, sample predictions | `runs/detect/yolo26m-p2-improved4-latest/` |

## FCSIT Formatting Rules (from `4 FYP report guide.pdf`)

- **Font:** Century Schoolbook 11 OR Times New Roman 12
- **Spacing:** Double-spaced
- **Alignment:** Full justified
- **Margins:** Top/bottom 3 cm, left/right 2.5 cm
- **Paper:** A4, 80 gsm, printed one-sided
- **Code snippets:** Minimal, 5–10 lines, labelled "Listing 4.x"
- **No IDE screenshots** of code

## Key Files for Writing Sections

### For 4.3 Backend System
- `main.py` — entry point, 2-process startup
- `core/ipc.py` — shared memory protocol, message types
- `core/ball_tracker.py` — Kalman filter (4-state constant-velocity)
- `core/calibration.py` — homography for court coordinates
- `core/game_logic.py` — side-out scoring FSM, serve detection (velocity threshold 120 px/frame)
- `core/database.py` — SQLite schema (matches, events, scores) with WAL mode
- `core/win_perf.py` — Windows iGPU keep-alive (mention briefly in 4.3.1)

### For 4.4 Web Dashboard
- `core/server.py` — Flask + MJPEG streaming
- `dashboard/index.html`, `dashboard/matches.html`, `dashboard/analysis.html`
- `dashboard/js/main.js`, `dashboard/js/analysis.js`
- `dashboard/js/chart.umd.min.js` — Chart.js library

## Ch 3 Consistency Points (important — don't contradict)

From FYP1 Ch 3.2.1 (pages 27–28):
- "standard USB webcam" → reframe as *"smartphone running DroidCam (a virtual webcam)"*
- "1080p resolution" ✓ matches 1920×1080
- "rear center of the court, elevated approximately 1.5 meters" ✓ matches fence setup
- "longitudinal angle" ✓ matches slight upward angle

## Pending Work Items (in order)

1. **Ch 4.3 Backend System** (all 5 subsections) — next focus
2. **Ch 4.4 Web Dashboard** (all 3 subsections)
3. **Ch 4.5 Summary**
4. **Capture Figure 4.1** — Roboflow annotation screenshot
5. **Capture Figures 4.2–4.5** — copy training result images from `runs/detect/yolo26m-p2-improved4-latest/`
6. **Verify Table 4.4 iteration numbers** against actual `results.csv` files in each run folder
7. **Apply FCSIT formatting** in Word after pasting all text

## Completed Drafts (paste-ready, in this file)

The finalised 4.1, 4.2.1, 4.2.2, and 4.2.3 drafts have been given to the user in conversation. If user wants them re-consolidated into one document for easy copying, request: *"Consolidate all drafted Ch 4 sections into one block."*

---

**Last updated:** 2026-04-18
