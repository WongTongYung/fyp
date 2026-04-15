"""
Extract frames from a video file for labeling in Roboflow.

Usage:
    python training/extract_frames.py                           # uses default video
    python training/extract_frames.py assets/FixedCamera.mp4    # custom video
    python training/extract_frames.py assets/FixedCamera.mp4 5  # every 5th frame
"""

import cv2
import os
import sys


def extract_frames(video_path="assets/FixedCamera.mp4", every_n=10):
    """Extract every Nth frame from the video for labeling."""

    output_dir = os.path.join("training", "frames")
    os.makedirs(output_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video: {video_path}")
        return

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"Video: {video_path}")
    print(f"Total frames: {total_frames}, FPS: {fps:.1f}, Duration: {total_frames/fps:.1f}s")
    print(f"Extracting every {every_n}th frame -> ~{total_frames // every_n} images")
    print(f"Output: {output_dir}/")

    count = 0
    saved = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        if count % every_n == 0:
            filename = os.path.join(output_dir, f"frame_{count:06d}.jpg")
            cv2.imwrite(filename, frame)
            saved += 1
        count += 1

    cap.release()
    print(f"\nDone! Saved {saved} frames to {output_dir}/")
    print("\nNext steps:")
    print(f"  1. Upload {output_dir}/ to Roboflow")
    print("  2. Label the ball in each image (draw bounding boxes)")
    print("  3. Export as YOLOv11 format")
    print("  4. Place dataset in training/ folder")
    print("  5. Run: python training/train.py")


if __name__ == "__main__":
    video = sys.argv[1] if len(sys.argv) > 1 else "assets/FixedCamera.mp4"
    every_n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    extract_frames(video, every_n)
