"""
Auto-label extracted frames using the existing trained YOLO model.
Generates YOLO-format .txt label files alongside each frame image.

Usage:
    python training/auto_label.py                    # default: conf=0.3
    python training/auto_label.py --conf 0.5         # higher confidence threshold
    python training/auto_label.py --model path/to/weights.pt  # custom model
"""

import argparse
import os
import glob
from ultralytics import YOLO


def auto_label(frames_dir="training/frames", model_path="models/yolo11m-custom.pt", conf=0.3):
    """Run inference on extracted frames and save YOLO-format labels."""

    if not os.path.exists(model_path):
        print(f"Error: Model not found at {model_path}")
        return

    if not os.path.exists(frames_dir):
        print(f"Error: Frames directory not found at {frames_dir}")
        print("Run extract_frames.py first.")
        return

    images = sorted(glob.glob(os.path.join(frames_dir, "*.jpg")) +
                    glob.glob(os.path.join(frames_dir, "*.png")))

    if not images:
        print(f"Error: No images found in {frames_dir}")
        return

    print(f"Model: {model_path}")
    print(f"Frames: {frames_dir} ({len(images)} images)")
    print(f"Confidence threshold: {conf}")
    print()

    model = YOLO(model_path)

    labeled = 0
    skipped = 0
    low_conf_frames = []

    for i, img_path in enumerate(images):
        results = model(img_path, verbose=False, conf=conf)
        result = results[0]

        boxes = result.boxes
        img_w, img_h = result.orig_shape[1], result.orig_shape[0]

        label_path = os.path.splitext(img_path)[0] + ".txt"

        if len(boxes) == 0:
            # Write empty label file so Roboflow knows it was processed
            with open(label_path, "w") as f:
                pass
            skipped += 1
            low_conf_frames.append(os.path.basename(img_path))
            continue

        with open(label_path, "w") as f:
            for box in boxes:
                cls = int(box.cls[0])
                x_center, y_center, w, h = box.xywhn[0].tolist()
                confidence = float(box.conf[0])
                f.write(f"{cls} {x_center:.6f} {y_center:.6f} {w:.6f} {h:.6f}\n")

                if confidence < conf + 0.15:
                    low_conf_frames.append(os.path.basename(img_path))

        labeled += 1

        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1}/{len(images)} frames...")

    print(f"\nDone! Processed {len(images)} frames:")
    print(f"  Labeled: {labeled} frames (have detections)")
    print(f"  No ball detected: {skipped} frames")

    unique_low_conf = sorted(set(low_conf_frames))
    if unique_low_conf:
        print(f"\n  Frames needing review ({len(unique_low_conf)} total):")
        for name in unique_low_conf[:20]:
            print(f"    - {name}")
        if len(unique_low_conf) > 20:
            print(f"    ... and {len(unique_low_conf) - 20} more")

    print(f"\nNext steps:")
    print(f"  1. Upload {frames_dir}/ to Roboflow (images + .txt labels together)")
    print(f"  2. Review and correct labels in Roboflow")
    print(f"  3. Export as YOLOv11 format")
    print(f"  4. Run: python training/train.py --fresh")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-label frames using trained YOLO model")
    parser.add_argument("--frames", default="training/frames", help="Path to frames directory")
    parser.add_argument("--model", default="models/yolo11m-custom.pt", help="Path to model weights")
    parser.add_argument("--conf", type=float, default=0.3, help="Confidence threshold (default: 0.3)")
    args = parser.parse_args()

    auto_label(frames_dir=args.frames, model_path=args.model, conf=args.conf)
