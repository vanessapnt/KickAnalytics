import numpy as np
from config import *
import cv2

class GameState:
    def __init__(self):
        self.score = {"red": 0, "blue": 0}
        self.ball_in_goal = False
        self.H_matrix = None
        self.pending_corners = None
        self.pending_fw = None
        self.pending_fh = None
        self.goal_top = None
        self.goal_bottom = None

game = GameState()

def build_goal_zones():
    offset_x = (FIELD_W - GOAL_W) / 2
    x1 = int(CANVAS_W * offset_x / FIELD_W)
    x2 = int(CANVAS_W * (offset_x + GOAL_W) / FIELD_W)
    game.goal_top = {"y1": 0, "y2": FIELD_Y0, "x1": x1, "x2": x2}
    game.goal_bottom = {"y1": FIELD_Y1, "y2": CANVAS_H, "x1": x1, "x2": x2}
    print(f"Goals: x={x1}->{x2}, top y=0->{FIELD_Y0}, bottom y={FIELD_Y1}->{CANVAS_H}")

def store_pending_calibration(corners, fw, fh):
    game.pending_corners = corners
    game.pending_fw = fw
    game.pending_fh = fh

def confirm_calibration():
    if game.pending_corners is None:
        return False
    compute_homography(game.pending_corners, game.pending_fw, game.pending_fh)
    build_goal_zones()
    game.pending_corners = None
    game.pending_fw = None
    game.pending_fh = None
    return True

def compute_homography(corners, fw, fh):
    src = np.float32(corners)
    dst = np.float32([
        [0, FIELD_Y0],
        [CANVAS_W, FIELD_Y0],
        [CANVAS_W, FIELD_Y1],
        [0, FIELD_Y1],
    ])
    game.H_matrix = cv2.getPerspectiveTransform(src, dst)
    print(f"Homography computed from frame {fw}x{fh}")

def apply_homography(px, py):
    if game.H_matrix is None:
        return None, None
    p = game.H_matrix @ np.array([px, py, 1.0])
    return float(p[0] / p[2]), float(p[1] / p[2])

def check_goal(x, y):
    if game.goal_top is None:
        return None
    in_top = game.goal_top["x1"] <= x <= game.goal_top["x2"] and game.goal_top["y1"] <= y <= game.goal_top["y2"]
    in_bottom = game.goal_bottom["x1"] <= x <= game.goal_bottom["x2"] and game.goal_bottom["y1"] <= y <= game.goal_bottom["y2"]
    if in_top or in_bottom:
        if not game.ball_in_goal:
            game.ball_in_goal = True
            return "blue" if in_top else "red"
    else:
        game.ball_in_goal = False
    return None