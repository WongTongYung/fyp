"""
Train or fine-tune YOLO for pickleball ball detection.

Usage:
    python training/train.py              # fine-tune from existing custom model
    python training/train.py --fresh      # train from pretrained YOLO11m base
    python training/train.py --yolo26p2   # train YOLO26m with P2 head (recommended)
"""

import sys
sys.path.insert(0, ".")
from ultralytics import YOLO
from config import TRAINING_DATA_PATH


def train_model(fresh=False, yolo26p2=False):
    data_path = TRAINING_DATA_PATH
    if yolo26p2:
        # YOLO26m with P2 small-object head — best for tiny ball detection
        # STAL + ProgLoss + P2 stride-4 detection
        print("Training YOLO26m-P2 architecture...")
        model = YOLO('yolo26m-p2.yaml').load('models/yolo26m.pt')
    elif fresh:
        # Start from pretrained YOLO11m base (download automatically)
        print("Training from pretrained YOLO11m base...")
        model = YOLO('yolo11m.pt')
    else:
        # Fine-tune from your existing custom model
        print("Fine-tuning from existing custom model...")
        model = YOLO('models/yolo11m-custom.pt')

    model.train(
        data=data_path,
        imgsz=640,              # P2 head at 1280 exceeds 6GB VRAM — 640 still gives 160x160 P2 grid
        device='0',
        batch=4,                # Reduced to fit GPU memory with P2 head
        epochs=100,
        workers=10,
        name='trained-results',
        patience=25,            # Stop if no improvement for 25 epochs
        lr0=0.005,              # Custom learning rate
        fliplr=0.5,             # 50% chance of horizontal flip
        degrees=0.0,            # No rotation — fixed camera angle
        mosaic=1.0,             # Combine 4 images — helps small datasets generalise
        copy_paste=0.3,         # Paste ball instances into other frames
        hsv_v=0.4,              # Brightness variation — handles indoor lighting changes
        resume=False,
    )

    print("\nTraining complete!")
    print("Best weights saved to: runs/detect/trained-results/weights/best.pt")
    print("\nTo use the new model, copy it:")
    print("  cp runs/detect/trained-results/weights/best.pt models/yolo11m-custom.pt")


if __name__ == '__main__':
    fresh = '--fresh' in sys.argv
    yolo26p2 = '--yolo26p2' in sys.argv
    train_model(fresh=fresh, yolo26p2=yolo26p2)
