import numpy as np
import cv2
import onnxruntime as ort
import mediapipe as mp
import time
from collections import deque, defaultdict
from datetime import datetime, time as dtime
from dataclasses import dataclass
from typing import Deque, Tuple, Dict
from ultralytics import YOLO

@dataclass
class TrackState:
    history: Deque[Tuple[int, float, float]]

class FallDetectionState:
    def __init__(self, window_size=16, target_size=(224, 224)):
        self.window_size = window_size
        self.target_size = target_size
        self.optical_flow_queue = deque(maxlen=window_size)
        self.pose_queue = deque(maxlen=window_size)
        self.previous_gray = None
        self.last_label = "Initializing..."
        self.last_probability = 0.0
        self.last_is_fall = False
        self.pose_estimator = mp.solutions.pose.Pose(static_image_mode=False, min_detection_confidence=0.5, min_tracking_confidence=0.3)

    def is_ready(self):
        return len(self.optical_flow_queue) == self.window_size and len(self.pose_queue) == self.window_size

    def update_last(self, label, probability, is_fall):
        self.last_label = label
        self.last_probability = probability
        self.last_is_fall = is_fall

class AloneFallDetectionState:
    def __init__(self, window_size=16, target_size=(224, 224), history_len=90):
        self.fall_state = FallDetectionState(window_size, target_size)
        self.history_len = history_len
        self.states = defaultdict(lambda: TrackState(history=deque(maxlen=history_len)))
        self.frame_id = 0
        self.last_person_count = 0
        self.last_alone_status = "normal"
        self.last_fall_detected = False
        self.last_fall_probability = 0.0
        self.last_alone_alert_time = 0  # Track last time alone alert was sent

def preprocess_frame(frame, target_size):
    resized = cv2.resize(frame, target_size)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return resized, gray

def compute_optical_flow(prev_gray, curr_gray, target_size):
    if prev_gray is None:
        return np.zeros((*target_size[::-1], 3), dtype=np.uint8)
    flow = cv2.calcOpticalFlowFarneback(prev_gray, curr_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    hsv = np.zeros((*target_size[::-1], 3), dtype=np.uint8)
    hsv[..., 0] = ang * 180 / np.pi / 2
    hsv[..., 1] = 255
    hsv[..., 2] = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX)
    flow_img = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    return flow_img

def extract_pose(frame, pose_estimator, flow_magnitude, mag_threshold=0.2):
    if flow_magnitude < mag_threshold:
        return np.zeros((17, 2), dtype=np.float32)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = pose_estimator.process(rgb)
    keypoints = np.zeros((17, 2), dtype=np.float32)
    if results.pose_landmarks:
        for i, lm in enumerate(results.pose_landmarks.landmark[:17]):
            keypoints[i] = [lm.x, lm.y]
    return keypoints

class FallONNXDetector:
    def __init__(self, model_path):
        sess_options = ort.SessionOptions()
        sess_options.log_severity_level = 3
        providers = ['CPUExecutionProvider']
        
        self.session = ort.InferenceSession(
            model_path, 
            sess_options=sess_options,
            providers=providers
        )
        self.input_names = [i.name for i in self.session.get_inputs()]
        self.output_names = [o.name for o in self.session.get_outputs()]

    def predict(self, optical_flow_seq, pose_seq):
        inputs = {
            self.input_names[0]: optical_flow_seq.astype(np.float32),
            self.input_names[1]: pose_seq.astype(np.float32)
        }
        outputs = self.session.run(self.output_names, inputs)
        logits = outputs[0][0]
        probability = 1.0 / (1.0 + np.exp(-logits))
        return float(probability), probability > 0.5

class AlonePersonDetector:
    def __init__(self, yolo_model_path="models/yolov10x.pt"):
        self.yolo_model = YOLO(yolo_model_path)
        self.conf_thresh = 0.6

    def detect_persons(self, frame):
        results = self.yolo_model.track(
            source=[frame],
            stream=False,
            tracker="bytetrack.yaml",
            conf=self.conf_thresh,
            classes=[0],
            verbose=False
        )
        
        person_count = 0
        detections = []
        
        if results and len(results) > 0:
            result = results[0]
            boxes = result.boxes
            
            if boxes is not None and len(boxes) > 0:
                xyxy = boxes.xyxy.cpu().numpy()
                ids = boxes.id.cpu().numpy() if boxes.id is not None else None
                confs = boxes.conf.cpu().numpy() if boxes.conf is not None else None
                
                for j in range(len(xyxy)):
                    tid = int(ids[j]) if ids is not None else -1
                    x1, y1, x2, y2 = xyxy[j].astype(int)
                    conf = float(confs[j]) if confs is not None else 0.0
                    
                    detections.append({
                        'track_id': tid,
                        'bbox': (x1, y1, x2, y2),
                        'confidence': conf
                    })
                    person_count += 1
        
        return person_count, detections

def get_risk_level(person_count, is_fall):
    if is_fall:
        return "red"  # Fall detected - highest priority (regardless of person count)
    elif person_count == 1:
        return "yellow"  # Alone but no fall
    elif person_count == 0:
        return "normal"  # No person detected
    else:
        return "normal"  # Multiple persons

def detect_alone_only(frame, person_detector: AlonePersonDetector):
    """
    Simplified alone detection function that only detects person count
    without fall detection processing
    """
    person_count, detections = person_detector.detect_persons(frame)
    
    if person_count == 1:
        detection_result = "alone"
        risk_level = "yellow"
    elif person_count == 0:
        detection_result = "no_person"
        risk_level = "normal"
    else:
        detection_result = "normal"
        risk_level = "normal"
    
    return risk_level, person_count, detection_result, frame

def detect_alone_and_fall(frame, state: AloneFallDetectionState, fall_detector: FallONNXDetector, 
                         person_detector: AlonePersonDetector, config, camera=None, threshold=None):
    if camera is not None:
        threshold = camera.ai_confidence_threshold
    else:
        threshold = threshold if threshold is not None else config["AI_CONFIDENCE_THRESHOLD"]

    state.frame_id += 1
    
    person_count, detections = person_detector.detect_persons(frame)
    
    for detection in detections:
        tid = detection['track_id']
        x1, y1, x2, y2 = detection['bbox']
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        
        if tid != -1:
            track_state = state.states[tid]
            track_state.history.append((state.frame_id, cx, cy))
    
    fall_detected = False
    fall_probability = 0.0
    
    # Always process for fall detection regardless of person count
    # because a fallen person might not be detected as "person" by YOLO
    resized, gray = preprocess_frame(frame, state.fall_state.target_size)
    flow_img = compute_optical_flow(state.fall_state.previous_gray, gray, state.fall_state.target_size)
    
    if state.fall_state.previous_gray is not None:
        flow = cv2.calcOpticalFlowFarneback(state.fall_state.previous_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        avg_mag = mag.mean()
    else:
        avg_mag = 0.0
    
    keypoints = extract_pose(resized, state.fall_state.pose_estimator, avg_mag)
    state.fall_state.previous_gray = gray
    state.fall_state.optical_flow_queue.append(flow_img)
    state.fall_state.pose_queue.append(keypoints)
    
    if state.fall_state.is_ready():
        optical_flow_array = np.stack(state.fall_state.optical_flow_queue)
        optical_flow_tensor = optical_flow_array.transpose(0, 3, 1, 2)
        optical_flow_tensor = np.expand_dims(optical_flow_tensor, 0)
        optical_flow_tensor = optical_flow_tensor.astype(np.float32) / 255.0
        
        pose_array = np.stack(state.fall_state.pose_queue)
        pose_tensor = np.expand_dims(pose_array, 0)
        pose_tensor = pose_tensor.astype(np.float32)
        
        fall_probability, is_fall = fall_detector.predict(optical_flow_tensor, pose_tensor)
        fall_detected = is_fall and fall_probability > threshold
    else:
        pass  # Fall detection not ready yet
    
    risk_level = get_risk_level(person_count, fall_detected)
    
    current_time = time.time()
    alone_cooldown = 0
    should_alert_alone = False
    
    if person_count == 1 and not fall_detected:
        # Check if enough time has passed since last alone alert
        if current_time - state.last_alone_alert_time >= alone_cooldown:
            should_alert_alone = True
            state.last_alone_alert_time = current_time
        else:
            remaining_time = alone_cooldown - (current_time - state.last_alone_alert_time)
    
    if fall_detected:
        detection_result = "fall"
    elif person_count == 1:
        detection_result = "alone"
    elif person_count == 0:
        detection_result = "no_person"
    else:
        detection_result = "normal"
    
    state.last_person_count = person_count
    state.last_alone_status = risk_level
    state.last_fall_detected = fall_detected
    state.last_fall_probability = fall_probability
    
    return risk_level, person_count, fall_detected, fall_probability, detection_result, frame, should_alert_alone

def detect_fall_legacy(frame, state: FallDetectionState, detector: FallONNXDetector, config, camera=None, threshold=None):
    if camera is not None:
        threshold = camera.ai_confidence_threshold
    else:
        threshold = threshold if threshold is not None else config["AI_CONFIDENCE_THRESHOLD"]

    resized, gray = preprocess_frame(frame, state.target_size)
    flow_img = compute_optical_flow(state.previous_gray, gray, state.target_size)
    if state.previous_gray is not None:
        flow = cv2.calcOpticalFlowFarneback(state.previous_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        avg_mag = mag.mean()
    else:
        avg_mag = 0.0
    keypoints = extract_pose(resized, state.pose_estimator, avg_mag)
    state.previous_gray = gray
    state.optical_flow_queue.append(flow_img)
    state.pose_queue.append(keypoints)
    if not state.is_ready():
        state.update_last("Analyzing...", 0.0, False)
        return False, 0.0, "Analyzing...", frame
    optical_flow_array = np.stack(state.optical_flow_queue)
    optical_flow_tensor = optical_flow_array.transpose(0, 3, 1, 2)
    optical_flow_tensor = np.expand_dims(optical_flow_tensor, 0)
    optical_flow_tensor = optical_flow_tensor.astype(np.float32) / 255.0
    pose_array = np.stack(state.pose_queue)
    pose_tensor = np.expand_dims(pose_array, 0)
    pose_tensor = pose_tensor.astype(np.float32)
    probability, is_fall = detector.predict(optical_flow_tensor, pose_tensor)
    detected = is_fall and probability > threshold
    label = "fall" if detected else "no_fall"
    state.update_last(label, probability, detected)
    return detected, probability, label, frame
