import cv2
import numpy as np
import onnxruntime as ort
from datetime import datetime, time as dtime

CLASSES = ["bed", "sleep", "sit"]

SKIP_FRAMES = 15
MOTION_THRESHOLD = 200000
MAX_MOTION_THRESHOLD = 70000000

def get_bed_roi(frame, roi_width=1000):
    h, w = frame.shape[:2]
    x1 = w // 2 - roi_width // 2
    x2 = w // 2 + roi_width // 2
    return frame[:, x1:x2], (x1, x2)

def preprocess_image(frame):
    roi, _ = get_bed_roi(frame, roi_width=1000)
    roi = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
    roi = cv2.resize(roi, (160, 160))
    image = roi.astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406])
    std = np.array([0.229, 0.224, 0.225])
    image = (image - mean) / std
    image = np.transpose(image, (2, 0, 1))
    image = np.expand_dims(image, 0)
    return image.astype(np.float32)

def is_in_time_window(start_hour, end_hour):
    now = datetime.now().time()
    start = dtime(start_hour, 0)
    end = dtime(end_hour, 0)
    if start < end:
        return start <= now < end
    else:
        return now >= start or now < end

class BedExitDetectionState:
    def __init__(self):
        self.ref_gray = None
        self.frame_idx = 0
        self.prev_class = None

def detect_bed_exit(
    frame,
    state: BedExitDetectionState,
    config,
    camera=None,
    model_path=None,
    threshold=None
):
    state.frame_idx += 1
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if state.ref_gray is None:
        state.ref_gray = gray
        state.frame_idx = 1
        return
    if state.frame_idx < SKIP_FRAMES:
        return

    diff = cv2.absdiff(gray, state.ref_gray)
    motion = np.sum(diff)
    if motion < MOTION_THRESHOLD or motion > MAX_MOTION_THRESHOLD:
        state.ref_gray = gray
        state.frame_idx = 0
        return False, 0.0, state.prev_class, frame
    if camera is not None:
        threshold = camera.ai_confidence_threshold

    if model_path is None:
        model_path = config["BED_EXIT_MODEL_PATH"]
    input_tensor = preprocess_image(frame)
    
    sess_options = ort.SessionOptions()
    sess_options.log_severity_level = 3
    providers = ['CPUExecutionProvider']
    
    session = ort.InferenceSession(
        model_path, 
        sess_options=sess_options,
        providers=providers
    )
    outputs = session.run(None, {'input': input_tensor})
    probabilities = outputs[0]
    predicted_class = np.argmax(probabilities, axis=1)[0]
    confidence = float(np.max(probabilities))
    current_class = CLASSES[predicted_class]
    detected = False
    if state.prev_class == 'sleep' and current_class == 'sit' and confidence > threshold:
        detected = True
    if confidence > threshold:
        state.prev_class = current_class
    state.ref_gray = gray
    state.frame_idx = 0
    return detected, confidence, current_class, frame 