import sys
sys.path.insert(0, ".")

from ultralytics import YOLO
from config import BALL_MODEL_PATH, TRAINING_DATA_PATH

if __name__ == '__main__':
    model = YOLO(BALL_MODEL_PATH)
    results = model.val(data=TRAINING_DATA_PATH, split="test")
