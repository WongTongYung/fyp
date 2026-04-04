"""
Train or fine-tune YOLO11m for pickleball ball detection.

Usage:
    python training/train.py              # fine-tune from existing custom model
    python training/train.py --fresh      # train from pretrained YOLO11m base
"""

import sys
from ultralytics import YOLO


def train_model(fresh=False):
    if fresh:
        # Start from pretrained YOLO11m base (download automatically)
        print("Training from pretrained YOLO11m base...")
        model = YOLO('yolo11m.pt')
    else:
        # Fine-tune from your existing custom model
        print("Fine-tuning from existing custom model...")
        model = YOLO('models/yolo11m-custom.pt')

    model.train(
        data='training/custom_dataset.yaml',
        imgsz=640,
        device='0',
        batch=16,
        epochs=100,
        workers=10,
        name='trained-results',
        patience=25,            # Stop if no improvement for 25 epochs
        lr0=0.005,              # Custom learning rate
        fliplr=0.5,             # 50% chance of horizontal flip
        degrees=15,             # Random rotation augmentation
        resume=False,
    )

    print("\nTraining complete!")
    print("Best weights saved to: runs/detect/trained-results/weights/best.pt")
    print("\nTo use the new model, copy it:")
    print("  cp runs/detect/trained-results/weights/best.pt models/yolo11m-custom.pt")


if __name__ == '__main__':
    fresh = '--fresh' in sys.argv
    train_model(fresh=fresh)
