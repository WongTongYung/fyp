import cv2
import numpy as np
import json
import os
import queue as _queue

COURT_FILE = "court.json"
_points = []


# ─────────────────────────────────────────────
# Option 2 — Automatic line detection
# ─────────────────────────────────────────────

def _detect_court_auto(frame):
    """
    Try to detect court boundary automatically using edge + Hough lines.
    Returns a (4,2) numpy array of corners or None if detection fails.
    """
    h, w = frame.shape[:2]

    # 1. Pre-process
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)

    # DEBUG — thread-safe: write images to disk instead of imshow
    cv2.imwrite("debug_edges.jpg", edges)

    # 2. Detect line segments
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180,
                             threshold=80,
                             minLineLength=w // 6,
                             maxLineGap=20)

    # DEBUG — draw detected Hough lines
    debug = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            cv2.line(debug, (x1, y1), (x2, y2), (0, 255, 0), 1)
    cv2.imwrite("debug_lines.jpg", debug)

    if lines is None:
        return None

    # 3. Split into horizontal and vertical lines by angle
    h_lines, v_lines = [], []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if angle < 25 or angle > 155:       # near-horizontal
            h_lines.append((x1, y1, x2, y2))
        elif 65 < angle < 115:              # near-vertical
            v_lines.append((x1, y1, x2, y2))

    if len(h_lines) < 2 or len(v_lines) < 2:
        return None

    # 4. Find boundary lines — constrain zones to avoid picking center lines
    def y_mid(l): return (l[1] + l[3]) / 2
    def x_mid(l): return (l[0] + l[2]) / 2

    # Horizontal: top must be upper 50%, bottom must be lower 50%
    top_candidates = [ln for ln in h_lines if h * 0.2 < y_mid(ln) < h * 0.5]
    bottom_candidates = [ln for ln in h_lines if y_mid(ln) > h * 0.5]
    # Vertical: left must be left 40%, right must be right 40%
    left_candidates   = [ln for ln in v_lines if x_mid(ln) < w * 0.4]
    right_candidates  = [ln for ln in v_lines if x_mid(ln) > w * 0.6]

    if not top_candidates or not bottom_candidates or not left_candidates or not right_candidates:
        return None

    top    = min(top_candidates,    key=y_mid)
    bottom = max(bottom_candidates, key=y_mid)
    left   = min(left_candidates,   key=x_mid)
    right  = max(right_candidates,  key=x_mid)

    # 5. Compute intersections of the 4 boundary lines
    def line_to_eq(seg):
        """Convert (x1,y1,x2,y2) to (a,b,c) where ax+by=c."""
        x1, y1, x2, y2 = seg
        a = y2 - y1
        b = x1 - x2
        c = a * x1 + b * y1
        return a, b, c

    def intersect(seg1, seg2):
        a1, b1, c1 = line_to_eq(seg1)
        a2, b2, c2 = line_to_eq(seg2)
        det = a1 * b2 - a2 * b1
        if abs(det) < 1e-6:
            return None
        x = (c1 * b2 - c2 * b1) / det
        y = (a1 * c2 - a2 * c1) / det
        return int(x), int(y)

    tl = intersect(top, left)
    tr = intersect(top, right)
    br = intersect(bottom, right)
    bl = intersect(bottom, left)

    if None in (tl, tr, br, bl):
        return None

    corners = np.array([tl, tr, br, bl], dtype=np.float32)

    # 6. Sanity check — corners should be inside the frame (with margin)
    margin = 20
    for cx, cy in corners:
        if not (-margin < cx < w + margin and -margin < cy < h + margin):
            return None

    # DEBUG — draw the final selected polygon on the original frame
    debug_poly = frame.copy()
    pts = corners.astype(np.int32)
    cv2.polylines(debug_poly, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
    labels = ["TL", "TR", "BR", "BL"]
    for i, (px, py) in enumerate(pts):
        cv2.circle(debug_poly, (px, py), 6, (0, 0, 255), -1)
        cv2.putText(debug_poly, labels[i], (px + 8, py - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    cv2.imwrite("debug_polygon.jpg", debug_poly)

    return corners


def _show_and_confirm(frame, court_poly, mode_label):
    """
    Show detected court overlay and ask user to confirm (ENTER) or
    switch to manual (M) or retry auto (R for auto mode).
    Returns court_poly if accepted, None if rejected.
    """
    preview = frame.copy()
    pts = court_poly.astype(np.int32)
    cv2.polylines(preview, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
    labels = ["TL", "TR", "BR", "BL"]
    for i, (px, py) in enumerate(pts):
        cv2.circle(preview, (px, py), 6, (0, 255, 0), -1)
        cv2.putText(preview, labels[i], (px + 8, py - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    cv2.putText(preview, f"{mode_label} | ENTER=accept  M=manual  R=retry auto",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

    window = "Court Detection"
    cv2.imshow(window, preview)
    while True:
        key = cv2.waitKey(0) & 0xFF
        if key == 13:           # ENTER — accept
            cv2.destroyWindow(window)
            return court_poly
        if key == ord('m'):     # M — go manual
            cv2.destroyWindow(window)
            return None
        if key == ord('r'):     # R — retry (caller handles)
            cv2.destroyWindow(window)
            return "retry"


# ─────────────────────────────────────────────
# Option 1 — Manual calibration (fallback)
# ─────────────────────────────────────────────

def _click_event(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN and len(_points) < 6:
        scale_x, scale_y = param if param else (1.0, 1.0)
        orig_x = int(x / scale_x)
        orig_y = int(y / scale_y)
        _points.append((orig_x, orig_y))
        labels = ["TL", "TR", "BR", "BL", "Net-L", "Net-R"]
        idx = len(_points) - 1
        print(f"  Point {len(_points)} ({labels[idx]}) set: ({orig_x}, {orig_y})")


MAX_DISPLAY_W, MAX_DISPLAY_H = 1280, 720
SEC_NAV_RANGE = 30   # ±seconds the user can navigate during manual calibration


def calibrate_court(frame, cap=None, start_pos=0, fps=30):
    """
    Manual fallback: user clicks 4 court corners.
    Order: top-left → top-right → bottom-right → bottom-left
    Display is scaled to fit the screen; clicks are mapped back to original resolution.

    If cap is provided (video file), A/D keys let the user step
    ±SEC_NAV_RANGE seconds around start_pos to find a cleaner frame.
    Navigating to a new frame resets any clicked points.
    """
    global _points
    _points = []

    fps = max(1, fps)
    current_sec = 0   # offset in seconds from start_pos
    current_frame = frame

    h, w = frame.shape[:2]
    scale = min(MAX_DISPLAY_W / w, MAX_DISPLAY_H / h, 1.0)
    disp_w, disp_h = int(w * scale), int(h * scale)

    window = "Manual Calibration - click 4 corners + 2 net points, then ENTER"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, disp_w, disp_h)
    cv2.setMouseCallback(window, _click_event, (scale, scale))

    print("\n[Calibration] Manual mode.")
    print("  Click: 1=TL  2=TR  3=BR  4=BL  5=Net-Left  6=Net-Right")
    if cap is not None:
        print(f"  A/D keys to navigate +-{SEC_NAV_RANGE}s (resets points)")
    print("  ENTER to confirm (after 6 points) | R to reset\n")

    while True:
        display = cv2.resize(current_frame, (disp_w, disp_h))
        preview = display.copy()

        point_labels = ["TL", "TR", "BR", "BL", "Net-L", "Net-R"]
        for i, (ox, oy) in enumerate(_points):
            pt = (int(ox * scale), int(oy * scale))
            color = (0, 255, 0) if i < 4 else (255, 255, 0)  # cyan for net points
            cv2.circle(preview, pt, 6, color, -1)
            cv2.putText(preview, point_labels[i], (pt[0] + 8, pt[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        if len(_points) >= 4:
            scaled_corners = [(int(ox * scale), int(oy * scale)) for ox, oy in _points[:4]]
            cv2.polylines(preview,
                          [np.array(scaled_corners, dtype=np.int32)],
                          isClosed=True, color=(0, 255, 0), thickness=2)
        if len(_points) == 6:
            # Draw net line in cyan
            nl = [(int(ox * scale), int(oy * scale)) for ox, oy in _points[4:6]]
            cv2.line(preview, nl[0], nl[1], (255, 255, 0), 2)

        nav_hint = f"  A/D=sec({current_sec:+d}/{SEC_NAV_RANGE})  " if cap is not None else "  "
        step = "corners" if len(_points) < 4 else "net" if len(_points) < 6 else "ENTER"
        cv2.putText(preview,
                    f"Next: {step} ({len(_points)}/6) |{nav_hint}ENTER=confirm  R=reset",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.imshow(window, preview)

        key = cv2.waitKey(1) & 0xFF

        if key == 13 and len(_points) == 6:   # ENTER
            break

        if key == ord('r'):
            _points = []
            print("  Reset.")
            continue

        # Second-based navigation (only when cap is available)
        if cap is not None:
            new_sec = None
            if key == ord('a') and current_sec > -SEC_NAV_RANGE:
                new_sec = current_sec - 1
            elif key == ord('d') and current_sec < SEC_NAV_RANGE:
                new_sec = current_sec + 1

            if new_sec is not None:
                target = max(0, start_pos + new_sec * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, target)
                ret, f = cap.read()
                if ret:
                    current_sec = new_sec
                    current_frame = f
                    _points = []   # reset clicks for new frame
                    print(f"  Offset: {current_sec:+d}s  (frame {target})")

    cv2.destroyWindow(window)

    # Restore cap to start_pos so the rest of the pipeline is unaffected
    if cap is not None:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_pos)

    return np.array(_points, dtype=np.float32)


# ─────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────

def _save(corners, net=None):
    """Save court as {"corners": [...], "net": [...] or null}."""
    payload = {"corners": corners.tolist()}
    payload["net"] = net.tolist() if net is not None else None
    with open(COURT_FILE, "w") as f:
        json.dump(payload, f)
    print(f"[Calibration] Court saved to {COURT_FILE}")


def load_court():
    """Return (corners, net) tuple.  net may be None.
    Backward-compatible: old flat-list format → net=None."""
    if not os.path.exists(COURT_FILE):
        return None
    with open(COURT_FILE, "r") as f:
        data = json.load(f)
    print(f"[Calibration] Court loaded from {COURT_FILE}")
    if isinstance(data, dict):
        corners = np.array(data["corners"], dtype=np.float32)
        net = np.array(data["net"], dtype=np.float32) if data.get("net") else None
        return corners, net
    # Old format: flat list of 4 corners
    return np.array(data, dtype=np.float32), None


def get_court(frame, mode="manual", cap=None, start_pos=0, fps=30):
    """
    mode='auto'   — try automatic detection, confirm with user, fallback to manual
    mode='manual' — skip auto, go straight to manual click
    mode='load'   — load from file only, skip detection entirely

    cap / start_pos / fps: optional video capture + frame index + fps so that
    manual calibration can let the user navigate ±SEC_NAV_RANGE seconds.

    Always saves result to court.json.
    """
    # Always try loading saved file first
    loaded = load_court()
    if loaded is not None:
        return loaded  # (corners, net) tuple

    if mode == "load":
        print("[Calibration] No court.json found. Run with mode='auto' or 'manual' first.")
        exit()

    corners = None
    net = None

    if mode == "auto":
        print("[Calibration] Attempting automatic court detection...")
        auto = _detect_court_auto(frame)
        if auto is not None:
            result = _show_and_confirm(frame, auto, "Auto-detected")
            if result not in ("retry", None):
                corners = result
                # Auto-detection doesn't find the net — user will need manual calibration
                # for net line, or it stays None (falls back to midpoint inference)
            else:
                corners = None

        if corners is None:
            print("[Calibration] Auto-detection failed or rejected — switching to manual.")
            all_pts = calibrate_court(frame, cap=cap, start_pos=start_pos, fps=fps)
            corners = all_pts[:4]
            net = all_pts[4:6] if len(all_pts) >= 6 else None

    elif mode == "manual":
        all_pts = calibrate_court(frame, cap=cap, start_pos=start_pos, fps=fps)
        corners = all_pts[:4]
        net = all_pts[4:6] if len(all_pts) >= 6 else None

    _save(corners, net)
    return corners, net


def is_in_court(cx, cy, court_poly):
    """Returns True if (cx, cy) is inside the court polygon."""
    result = cv2.pointPolygonTest(
        court_poly.astype(np.int32), (float(cx), float(cy)), False
    )
    return result >= 0


def get_court_half(cx, cy, court_poly, net_line=None):
    """Return 'near' or 'far' depending on which half of the court (cx, cy) is on.

    If net_line is provided (2 points), it is used as the midline.
    Otherwise falls back to midpoint of left edge (TL→BL) / right edge (TR→BR).
    'far'  = top half (lower y, closer to camera far end)
    'near' = bottom half (higher y, closer to camera near end)
    """
    if net_line is not None and len(net_line) >= 2:
        mid_left, mid_right = net_line[0], net_line[1]
    else:
        tl, tr, br, bl = court_poly[:4]
        mid_left = (tl + bl) / 2.0
        mid_right = (tr + br) / 2.0

    # Cross product of midline vector with vector to the point.
    # Positive = below midline (near), negative = above midline (far).
    mx, my = mid_right[0] - mid_left[0], mid_right[1] - mid_left[1]
    px, py = cx - mid_left[0], cy - mid_left[1]
    cross = mx * py - my * px
    return "near" if cross >= 0 else "far"


# ─────────────────────────────────────────────
# Homography — pixel ↔ real-world court coords
# ─────────────────────────────────────────────

# Pickleball court dimensions in cm
COURT_W = 609.6      # 20ft width
COURT_L = 1341.12    # 44ft length
NET_Y   = 670.56     # net at center (22ft)
KITCHEN_NEAR = 457.2  # 15ft
KITCHEN_FAR  = 883.92 # 29ft
CENTER_X = 304.8      # 10ft (center service line)


def compute_homography(corners, net=None):
    """Compute pixel→court homography from calibration points.
    corners: 4 points [TL, TR, BR, BL] in pixel coords.
    net: 2 points [net_left, net_right] in pixel coords, or None.
    Returns H (3x3 ndarray).
    """
    dst_corners = np.array([
        [0, 0], [COURT_W, 0], [COURT_W, COURT_L], [0, COURT_L]
    ], dtype=np.float32)

    if net is not None and len(net) >= 2:
        src = np.vstack([corners[:4], net[:2]]).astype(np.float32)
        dst = np.vstack([dst_corners,
                         [[0, NET_Y], [COURT_W, NET_Y]]]).astype(np.float32)
        H, _ = cv2.findHomography(src, dst)
    else:
        H = cv2.getPerspectiveTransform(
            corners[:4].astype(np.float32), dst_corners)
    return H


def pixel_to_court(px, py, H):
    """Transform a pixel coordinate to court coordinates (cm)."""
    pt = np.array([[[px, py]]], dtype=np.float64)
    out = cv2.perspectiveTransform(pt, H)
    return float(out[0][0][0]), float(out[0][0][1])


def calibration_thread(calib_queue, court_container, stop_event):
    """
    Background thread — keeps trying _detect_court_auto() on incoming frames
    until the court is found, then updates court_container and stops.
    """
    print("Starting calibration thread...")
    while not stop_event.is_set():
        with court_container["lock"]:
            if court_container["poly"] is not None:
                break
        try:
            frame = calib_queue.get(timeout=1)
        except _queue.Empty:
            continue
        poly = _detect_court_auto(frame)
        if poly is not None:
            with court_container["lock"]:
                court_container["poly"] = poly
                _save(poly)  # auto-detect: no net line
            print("[Calibration] Court detected automatically!")
            break
    print("Calibration thread stopped.")
