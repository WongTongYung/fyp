"""
Fine-tune YOLO for pickleball ball detection.

Usage:
    python training/train.py

Fine-tunes from the model at config.BALL_MODEL_PATH on the dataset at
config.TRAINING_DATA_PATH.
"""

import sys
sys.path.insert(0, ".")
from ultralytics import YOLO
from config import TRAINING_DATA_PATH, BALL_MODEL_PATH


def train_model():
    print(f"Fine-tuning from {BALL_MODEL_PATH}...")
    model = YOLO(BALL_MODEL_PATH)

    model.train(
        data=TRAINING_DATA_PATH,
        imgsz=640,
        device='0',
        batch=4,
        epochs=100,
        workers=10,
        name='trained-results',
        patience=25,
        lr0=0.005,
        fliplr=0.5,
        degrees=0.0,
        mosaic=1.0,
        copy_paste=0.3,
        hsv_v=0.4,
        resume=False,
    )

    print("\nTraining complete!")
    print("Best weights saved to: runs/detect/trained-results/weights/best.pt")
    print("\nTo use the new model, copy it:")
    print(f"  cp runs/detect/trained-results/weights/best.pt {BALL_MODEL_PATH}")


if __name__ == '__main__':
    train_model()
