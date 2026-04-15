import json
import logging
import os

import cv2
import numpy as np

from config import COURT_W, COURT_L, NET_Y, COURT_FILE


# --- Manual calibration ---

def calibrate_court(frame):
    """User clicks 4 court corners + 2 net points on a frame."""
    points = []
    labels = ["TL", "TR", "BR", "BL", "Net-L", "Net-R"]

    def on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 6:
            scale_x, scale_y = param
            points.append((int(x / scale_x), int(y / scale_y)))
            print(f"  Point {len(points)} ({labels[len(points)-1]}) set")

    h, w = frame.shape[:2]
    scale = min(1280 / w, 720 / h, 1.0)
    disp_w, disp_h = int(w * scale), int(h * scale)

    window = "Calibration - click 4 corners + 2 net points, ENTER to confirm"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, disp_w, disp_h)
    cv2.setMouseCallback(window, on_click, (scale, scale))

    while True:
        preview = cv2.resize(frame, (disp_w, disp_h)).copy()
        for i, (ox, oy) in enumerate(points):
            pt = (int(ox * scale), int(oy * scale))
            color = (0, 255, 0) if i < 4 else (255, 255, 0)
            cv2.circle(preview, pt, 6, color, -1)
            cv2.putText(preview, labels[i], (pt[0]+8, pt[1]-8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        if len(points) >= 4:
            pts = [(int(ox*scale), int(oy*scale)) for ox, oy in points[:4]]
            cv2.polylines(preview, [np.array(pts)], True, (0, 255, 0), 2)
        if len(points) == 6:
            nl = [(int(ox*scale), int(oy*scale)) for ox, oy in points[4:6]]
            cv2.line(preview, nl[0], nl[1], (255, 255, 0), 2)
        cv2.imshow(window, preview)

        key = cv2.waitKey(1) & 0xFF
        if key == 13 and len(points) == 6:
            break
        if key == ord('r'):
            points.clear()

    cv2.destroyWindow(window)
    return np.array(points, dtype=np.float32)


# --- Save / Load ---

def _save(corners, net=None):
    payload = {"corners": corners.tolist()}
    payload["net"] = net.tolist() if net is not None else None
    with open(COURT_FILE, "w") as f:
        json.dump(payload, f)
    logging.info("[Calibration] Court saved to %s", COURT_FILE)


def load_court():
    if not os.path.exists(COURT_FILE):
        return None
    with open(COURT_FILE, "r") as f:
        data = json.load(f)
    logging.info("[Calibration] Court loaded from %s", COURT_FILE)
    corners = np.array(data["corners"], dtype=np.float32)
    net = np.array(data["net"], dtype=np.float32) if data.get("net") else None
    return corners, net


def get_court(frame):
    """Load court from file, or run manual calibration if not found."""
    loaded = load_court()
    if loaded is not None:
        return loaded
    all_pts = calibrate_court(frame)
    corners = all_pts[:4]
    net = all_pts[4:6] if len(all_pts) >= 6 else None
    _save(corners, net)
    return corners, net


# --- Court helpers ---

def is_in_court(cx, cy, court_poly):
    """Returns True if (cx, cy) is inside the court polygon."""
    result = cv2.pointPolygonTest(
        court_poly.astype(np.int32), (float(cx), float(cy)), False)
    return result >= 0


def get_court_half(cx, cy, court_poly, net_line=None):
    """Return 'near' or 'far' depending on which half of the court."""
    if net_line is not None and len(net_line) >= 2:
        mid_left, mid_right = net_line[0], net_line[1]
    else:
        tl, tr, br, bl = court_poly[:4]
        mid_left, mid_right = (tl + bl) / 2.0, (tr + br) / 2.0
    mx, my = mid_right[0] - mid_left[0], mid_right[1] - mid_left[1]
    px, py = cx - mid_left[0], cy - mid_left[1]
    return "near" if (mx * py - my * px) >= 0 else "far"


# --- Homography ---
def compute_homography(corners, net=None):
    """Compute pixel to court homography from calibration points."""
    dst = np.array([
        [0, 0], [COURT_W, 0], [COURT_W, COURT_L], [0, COURT_L]
    ], dtype=np.float32)
    if net is not None and len(net) >= 2:
        src = np.vstack([corners[:4], net[:2]]).astype(np.float32)
        dst = np.vstack([dst, [[0, NET_Y], [COURT_W, NET_Y]]]).astype(np.float32)
        H, _ = cv2.findHomography(src, dst)
    else:
        H = cv2.getPerspectiveTransform(corners[:4].astype(np.float32), dst)
    return H


def pixel_to_court(px, py, H):
    """Transform a pixel coordinate to court coordinates (cm)."""
    pt = np.array([[[px, py]]], dtype=np.float64)
    out = cv2.perspectiveTransform(pt, H)
    return float(out[0][0][0]), float(out[0][0][1])
