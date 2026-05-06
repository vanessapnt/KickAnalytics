import cv2
import numpy as np
import onnxruntime as ort
import os

CONF_THRESH = 0.70

_int8_path  = os.path.join(os.path.dirname(__file__), "model_int8.onnx")
_model_path = _int8_path if os.path.exists(_int8_path) else \
              os.path.join(os.path.dirname(__file__), "model.onnx")
print(f"[vision] Loading model from {_model_path}...")

_opts = ort.SessionOptions()
_opts.intra_op_num_threads = 3
_opts.inter_op_num_threads = 1
_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
_opts.enable_mem_pattern = True
_opts.enable_cpu_mem_arena = True

sess       = ort.InferenceSession(_model_path, sess_options=_opts)
input_name = sess.get_inputs()[0].name
print("[vision] Model loaded")

def detect_ball(frame):
    img = cv2.resize(frame, (640, 640))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    img = np.ascontiguousarray(np.transpose(img, (2, 0, 1)))[np.newaxis]
    preds    = sess.run(None, {input_name: img})[0][0]
    best_idx = np.argmax(preds[4])
    conf     = float(preds[4][best_idx])
    if conf < CONF_THRESH:
        return None, None, conf
    return float(preds[0][best_idx]), float(preds[1][best_idx]), conf

def detect_field_corners(frame):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    l = clahe.apply(l)
    frame_norm = cv2.cvtColor(cv2.merge([l,a,b]), cv2.COLOR_LAB2BGR)
    
    hsv = cv2.cvtColor(frame_norm, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (30, 15, 30), (90, 255, 255))
    
    kernel = np.ones((25, 25), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    h, w = frame.shape[:2]
    min_area = (w * h) * 0.01
    valid_contours = [c for c in contours if cv2.contourArea(c) > min_area]

    if not valid_contours:
        return None

    largest = max(valid_contours, key=cv2.contourArea)
    peri = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, 0.02 * peri, True)
    if len(approx) != 4:
        rect = cv2.minAreaRect(largest)
        box = cv2.boxPoints(rect)
        approx = box.reshape(4, 1, 2).astype(float)
    pts4 = approx.reshape(4, 2).astype(float)

    x_min = pts4[:, 0].min()
    x_max = pts4[:, 0].max()

    top_n = sorted(valid_contours, key=cv2.contourArea, reverse=True)[:7]
    all_points = np.vstack(top_n).reshape(-1, 2).astype(float)
    y_min = all_points[:, 1].min()
    y_max = all_points[:, 1].max()

    tl = [x_min, y_min]
    tr = [x_max, y_min]
    br = [x_max, y_max]
    bl = [x_min, y_max]

    print(f"[CALIB] corners: tl={tl} tr={tr} br={br} bl={bl}")
    return [tl, tr, br, bl]