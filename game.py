import numpy as np
from config import *
import cv2

class GameState:
    def __init__(self):
        self.score = {"red": 0, "blue": 0}
        self.ball_in_goal = False
        self.H_matrix = None  # camera frame -> canvas
        self.pending_corners = None  # corners waiting for confirmation
        self.pending_fw = None
        self.pending_fh = None
        self.goal_top = None
        self.goal_bottom = None
        # Kalman filter state : [x, y, vx, vy]
        self.kx = np.array([[CANVAS_W / 2], [CANVAS_H / 2], [0], [0]], float)
        self.P  = np.eye(4) * 500

game = GameState()

def build_goal_zones():
    if any(v is None for v in [FIELD_W, FIELD_H, GOAL_W, GOAL_DEPTH_CM]):
        print("Field dimensions not set: goal detection disabled")
        return
    depth_px = int(CANVAS_H * GOAL_DEPTH_CM / FIELD_H)
    offset_x = (FIELD_W - GOAL_W) / 2
    x1 = int(CANVAS_W * offset_x / FIELD_W)
    x2 = int(CANVAS_W * (offset_x + GOAL_W) / FIELD_W)
    game.goal_top    = {"y1": 0,                   "y2": depth_px,   "x1": x1, "x2": x2}
    game.goal_bottom = {"y1": CANVAS_H - depth_px, "y2": CANVAS_H,   "x1": x1, "x2": x2}
    print(f"Goals: x={x1}->{x2}, top y=0->{depth_px}, bottom y={CANVAS_H-depth_px}->{CANVAS_H}")

# called when camera sends calibration_preview, before user confirms
def store_pending_calibration(corners, fw, fh):
    game.pending_corners = corners
    game.pending_fw      = fw
    game.pending_fh      = fh

def confirm_calibration():
    if game.pending_corners is None:
        return False
    compute_homography(game.pending_corners, game.pending_fw, game.pending_fh)
    build_goal_zones()
    reset_kalman()
    game.pending_corners = None
    game.pending_fw      = None
    game.pending_fh      = None
    return True

# def compute_homography(corners, fw, fh):
#     print(f"src corners: {corners}")
#     print(f"dst corners: [[0,0],[{CANVAS_W},0],[{CANVAS_W},{CANVAS_H}],[0,{CANVAS_H}]]")
#     # src : field corners in the frame -> dst : canvas corners
#     src = np.float32(corners)
#     dst = np.float32([[0, 0], [CANVAS_W, 0], [CANVAS_W, CANVAS_H], [0, CANVAS_H]])
#     A = []
#     for i in range(4):
#     # 8 linear equations for 8 unknowns (H * src = dst)
#     # H * [sx, sy, 1] = [px, py, pz]  →  [px/pz, py/pz] = [dx, dy]
#     #  [[h0, h1, h2],     [sx]     [h0*sx + h1*sy + h2*1]   [px]
#     #   [h3, h4, h5],  *  [sy]  =  [h3*sx + h4*sy + h5*1] = [py]
#     #   [h6, h7, 1 ]]     [1 ]     [h6*sx + h7*sy + 1*1 ]   [pz]
#         sx, sy = src[i]
#         dx, dy = dst[i]
#         A.append([-sx, -sy, -1,   0,   0,  0, sx*dx, sy*dx, dx])
#         A.append([  0,   0,  0, -sx, -sy, -1, sx*dy, sy*dy, dy])
#     A   = np.array(A, dtype=float)
#     aug = np.hstack([A[:8, :8], A[:8, 8:9]])
#     for col in range(8):
#         mr = col + np.argmax(np.abs(aug[col:, col]))
#         aug[[col, mr]] = aug[[mr, col]]
#         aug[col] /= aug[col, col]
#         for row in range(8):
#             if row != col:
#                 aug[row] -= aug[row, col] * aug[col]
#     h = aug[:, 8]
#     game.H_matrix = np.array([
#         [h[0], h[1], h[2]],
#         [h[3], h[4], h[5]],
#         [h[6], h[7], 1.0 ],
#     ])
#     print(f"Homography computed from frame {fw}x{fh}")

def compute_homography(corners, fw, fh):
    src = np.float32(corners)
    dst = np.float32([[0, 0], [CANVAS_W, 0], [CANVAS_W, CANVAS_H], [0, CANVAS_H]])
    game.H_matrix = cv2.getPerspectiveTransform(src, dst)
    print(f"Homography computed from frame {fw}x{fh}")

def apply_homography(px, py):
    if game.H_matrix is None:
        return None, None
    p = game.H_matrix @ np.array([px, py, 1.0])
    return float(p[0] / p[2]), float(p[1] / p[2])

# state transition matrix : x(t+1) = F * x(t)  (constant velocity model)
F  = np.array([[1,0,1,0],[0,1,0,1],[0,0,1,0],[0,0,0,1]], float)
Hk = np.array([[1,0,0,0],[0,1,0,0]], float) # observation matrix : we only observe x and y
Q  = np.eye(4) * 0.1  # process noise
R  = np.eye(2) * 5.0  # measurement noise

def kalman_update(mx, my):
    # predict
    game.kx = F @ game.kx
    game.P  = F @ game.P @ F.T + Q
    # update
    z = np.array([[mx], [my]])
    S = Hk @ game.P @ Hk.T + R
    K = game.P @ Hk.T @ np.linalg.inv(S)
    game.kx = game.kx + K @ (z - Hk @ game.kx)
    game.P  = (np.eye(4) - K @ Hk) @ game.P
    return float(game.kx[0]), float(game.kx[1])

def reset_kalman():
    game.kx = np.array([[CANVAS_W / 2], [CANVAS_H / 2], [0], [0]], float)
    game.P  = np.eye(4) * 500

def between_posts(y, zone):
    return zone["y1"] <= y <= zone["y2"]

def predict_next(x, y):
    vx = float(game.kx[2])
    vy = float(game.kx[3])
    return x + vx, y + vy

def between_posts(x, zone):
    return zone["x1"] <= x <= zone["x2"]

def check_goal(x, y):
    if game.goal_top is None:
        return None

    in_top    = game.goal_top["x1"] <= x <= game.goal_top["x2"] and game.goal_top["y1"]    <= y <= game.goal_top["y2"]
    in_bottom = game.goal_bottom["x1"] <= x <= game.goal_bottom["x2"] and game.goal_bottom["y1"] <= y <= game.goal_bottom["y2"]

    if in_top or in_bottom:
        if not game.ball_in_goal:
            game.ball_in_goal = True
            return "blue" if in_top else "red"
    else:
        game.ball_in_goal = False

    return None