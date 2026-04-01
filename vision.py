import cv2
import numpy as np
import onnxruntime as ort
import os

CONF_THRESH = 0.25

_model_path = os.path.join(os.path.dirname(__file__), "model.onnx")
print(f"[vision] Loading model from {_model_path}...")
sess       = ort.InferenceSession(_model_path)
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
    hsv    = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask   = cv2.inRange(hsv, (35, 20, 40), (85, 255, 255))
    kernel = np.ones((15, 15), np.uint8)
    mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    pts    = cv2.findNonZero(mask)
    if pts is None:
        return None
    hull   = cv2.convexHull(pts)
    approx = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
    if len(approx) != 4:
        print(f"[CALIB] approxPolyDP found {len(approx)} points, expected 4")
        return None
    pts4 = approx.reshape(4, 2)
    s    = pts4.sum(axis=1)
    d    = np.diff(pts4, axis=1).flatten()
    tl   = pts4[s.argmin()].tolist()
    br   = pts4[s.argmax()].tolist()
    tr   = pts4[d.argmin()].tolist()
    bl   = pts4[d.argmax()].tolist()
    print(f"[CALIB] corners: tl={tl} tr={tr} br={br} bl={bl}")
    return [tl, tr, br, bl]