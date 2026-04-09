import cv2
import numpy as np
import onnxruntime as ort
import os

CONF_THRESH = 0.25

_model_path = os.path.join(os.path.dirname(__file__), "model.onnx")
print(f"[vision] Loading model from {_model_path}...")

# Limiter ONNX à 1 thread interne pour ne pas saturer les 2 CPU Cloud Run
_opts = ort.SessionOptions()
_opts.intra_op_num_threads = 2   # 2 threads ONNX sur 4 CPU dispo
_opts.inter_op_num_threads = 1   # 1 suffit pour le graph scheduling
_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

sess       = ort.InferenceSession(_model_path, sess_options=_opts)
input_name = sess.get_inputs()[0].name
print("[vision] Model loaded")

def detect_ball(frame):
    img = cv2.resize(frame, (640, 640))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    img = np.expand_dims(np.transpose(img, (2, 0, 1)), 0)
    preds    = sess.run(None, {input_name: img})[0][0]
    best_idx = np.argmax(preds[4])
    conf     = float(preds[4][best_idx])
    if conf < CONF_THRESH:
        return None, None, conf
    return float(preds[0][best_idx]), float(preds[1][best_idx]), conf

def detect_field_corners(frame):
    # Normaliser la luminosité avec CLAHE
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    l = clahe.apply(l)
    frame_norm = cv2.cvtColor(cv2.merge([l,a,b]), cv2.COLOR_LAB2BGR)

    # Détecter le vert
    hsv = cv2.cvtColor(frame_norm, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (30, 15, 30), (90, 255, 255))

    # Morphologie plus agressive
    kernel = np.ones((25, 25), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    # Trouver le plus grand contour
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)

    # Approx polygone
    peri = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, 0.02 * peri, True)

    if len(approx) != 4:
        # Fallback : utiliser la bounding box du plus grand contour vert
        rect = cv2.minAreaRect(largest)
        box = cv2.boxPoints(rect)
        approx = box.reshape(4, 1, 2).astype(int)

    pts4 = approx.reshape(4, 2).astype(float)
    s = pts4.sum(axis=1)
    d = np.diff(pts4, axis=1).flatten()
    tl = pts4[s.argmin()].tolist()
    br = pts4[s.argmax()].tolist()
    tr = pts4[d.argmin()].tolist()
    bl = pts4[d.argmax()].tolist()

    return [tl, tr, br, bl]