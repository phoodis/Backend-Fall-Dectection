import os
import json
import numpy as np
import cv2
import time
import onnxruntime as ort
from collections import deque, defaultdict
from ultralytics import YOLO
import mediapipe as mp

try:
    import torchvision.transforms as transforms
    import torchvision.models as models
    import torch
    import torch.nn as nn
    from torchvision.models import ResNet50_Weights
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

class V2ONNXFallDetectionState:
    def __init__(self, sequence_length=4):
        self.sequence_length = sequence_length
        self.target_size = (224, 224)
        self.frame_buffer = deque(maxlen=60)
        self.optical_flow_queue = deque(maxlen=sequence_length)
        self.pose_queue = deque(maxlen=sequence_length)
        self.pose_estimator = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            enable_segmentation=False,
            min_detection_confidence=0.5
        )
        self.previous_gray = None
        self.last_detection = None
        self.last_probability = 0.0
        self.last_detected = False

    def is_ready(self):
        return (len(self.optical_flow_queue) >= self.sequence_length and 
                len(self.pose_queue) >= self.sequence_length and
                len(self.frame_buffer) >= 4)

    def update_last(self, detection, probability, detected):
        self.last_detection = detection
        self.last_probability = probability
        self.last_detected = detected

class V2AloneFallDetectionState:
    def __init__(self):
        self.fall_state = V2ONNXFallDetectionState()
        self.frame_id = 0
        self.states = defaultdict(lambda: type('TrackState', (), {'history': deque(maxlen=30)})())
        self.last_alone_alert_time = 0
        self.last_person_count = 0
        self.last_alone_status = "normal"
        self.last_fall_detected = False
        self.last_fall_probability = 0.0

def preprocess_frame_v2(frame, target_size):
    resized = cv2.resize(frame, target_size)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return resized, gray

def compute_optical_flow_v2(prev_gray, curr_gray, target_size):
    if prev_gray is None:
        return np.zeros((*target_size, 2), dtype=np.float32)
    
    try:
        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, curr_gray, None, 
            0.5, 3, 15, 3, 5, 1.2, 0
        )
        
        if flow is not None:
            flow_resized = cv2.resize(flow, target_size)
            return flow_resized.astype(np.float32)
        else:
            return np.zeros((*target_size, 2), dtype=np.float32)
            
    except Exception:
        return np.zeros((*target_size, 2), dtype=np.float32)

def extract_pose_v2(frame, pose_estimator, motion_magnitude):
    try:
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose_estimator.process(frame_rgb)
        
        if results.pose_landmarks:
            keypoints = []
            for landmark in results.pose_landmarks.landmark[:17]:
                keypoints.extend([landmark.x, landmark.y])
            keypoints.append(motion_magnitude)
            while len(keypoints) < 35:
                keypoints.append(0.0)
            return np.array(keypoints[:35], dtype=np.float32)
        else:
            return np.zeros(35, dtype=np.float32)
    except Exception:
        return np.zeros(35, dtype=np.float32)

class FeatureExtractorONNX:
    def __init__(self, device='cpu'):
        self.device = device
        
        if TORCH_AVAILABLE:
            self.model = models.resnet50(weights=ResNet50_Weights.DEFAULT)
            self.model = nn.Sequential(*list(self.model.children())[:-1])
            self.model.eval()
            
            self.preprocess = transforms.Compose([
                transforms.ToPILImage(),
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
            ])
        else:
            self.model = None
            self.preprocess = None

    def extract_rgb_features(self, frames):
        if not TORCH_AVAILABLE or self.model is None:
            return np.zeros(2048, dtype=np.float32)
        
        try:
            torch.manual_seed(42)
            selected_frames = frames[::4] if len(frames) > 4 else frames
            if len(selected_frames) > 4:
                selected_frames = selected_frames[:4]
            
            tensors = []
            for frame in selected_frames:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                tensor = self.preprocess(frame_rgb)
                tensors.append(tensor)
            
            if tensors:
                batch = torch.stack(tensors)
                with torch.no_grad():
                    features = self.model(batch)
                    features = features.view(features.size(0), -1)
                    rgb_features = features.mean(dim=0).numpy()
                    
                if len(rgb_features) > 2048:
                    rgb_features = rgb_features[:2048]
                elif len(rgb_features) < 2048:
                    rgb_features = np.pad(rgb_features, (0, 2048 - len(rgb_features)))
                
                return rgb_features.astype(np.float32)
            else:
                return np.zeros(2048, dtype=np.float32)
                
        except Exception:
            return np.zeros(2048, dtype=np.float32)

    def extract_flow_features(self, frames):
        if len(frames) < 2:
            return np.zeros(236, dtype=np.float32)
        
        try:
            np.random.seed(42)
            flows = []
            for i in range(0, len(frames) - 1, 5):
                if i + 5 >= len(frames):
                    break
                    
                gray1 = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
                gray2 = cv2.cvtColor(frames[i + 5], cv2.COLOR_BGR2GRAY)
                
                flow = cv2.calcOpticalFlowFarneback(
                    gray1, gray2, None, 0.5, 3, 15, 3, 5, 1.2, cv2.OPTFLOW_FARNEBACK_GAUSSIAN
                )
                
                if flow is not None:
                    flows.append(flow)
            
            if not flows:
                return np.zeros(236, dtype=np.float32)
            
            flows = np.array(flows)
            
            max_flow = np.percentile(np.sqrt(flows[..., 0]**2 + flows[..., 1]**2), 99)
            if max_flow > 0:
                flows = np.clip(flows, -max_flow, max_flow) / max_flow
            
            magnitude = np.sqrt(flows[..., 0]**2 + flows[..., 1]**2)
            features = np.concatenate([
                np.mean(flows[..., 0], axis=(1, 2)),
                np.mean(flows[..., 1], axis=(1, 2)),
                np.mean(magnitude, axis=(1, 2)),
                np.std(magnitude, axis=(1, 2))
            ])
            
            if len(features) < 236:
                features = np.pad(features, (0, 236 - len(features)))
            
            return features[:236].astype(np.float32)
            
        except Exception:
            return np.zeros(236, dtype=np.float32)

    def extract_pose_features(self, frames, timing_enabled=False):
        np.random.seed(42)
        
        if timing_enabled:
            start_pose = time.time()
        
        pose_features = np.zeros(136, dtype=np.float32)
        
        if timing_enabled:
            pose_time = time.time() - start_pose
            return pose_features, {'pose_time': pose_time}
        
        return pose_features

class V2ONNXFallDetector:
    def __init__(self, model_dir, device='cpu'):
        self.device = device
        
        onnx_path = os.path.join(model_dir, 'deepsvdd_model.onnx')
        
        providers = ['CPUExecutionProvider']
        if device == 'cuda':
            providers.insert(0, 'CUDAExecutionProvider')
        
        session_options = ort.SessionOptions()
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        
        self.onnx_session = ort.InferenceSession(onnx_path, session_options, providers=providers)
        
        norm_path = os.path.join(model_dir, 'normalization.json')
        with open(norm_path, 'r') as f:
            norm_data = json.load(f)
            self.mean = np.array(norm_data['mean'], dtype=np.float32)
            self.std = np.array(norm_data['std'], dtype=np.float32)
        
        threshold_path = os.path.join(model_dir, 'threshold.json')
        with open(threshold_path, 'r') as f:
            self.threshold = json.load(f)['threshold']
        
        center_path = os.path.join(model_dir, 'center.npy')
        self.center = np.load(center_path).astype(np.float32)
        
        self.feature_extractor = FeatureExtractorONNX(device)

    def predict(self, frames, pose_sequence):
        try:
            torch.manual_seed(42)
            np.random.seed(42)
            
            rgb_features = self.feature_extractor.extract_rgb_features(frames)
            flow_features = self.feature_extractor.extract_flow_features(frames)
            pose_features = self.feature_extractor.extract_pose_features(frames)
            
            combined_features = np.concatenate([rgb_features, flow_features, pose_features])
            normalized_features = (combined_features - self.mean) / self.std
            
            input_data = normalized_features.astype(np.float32).reshape(1, -1)
            outputs = self.onnx_session.run(['output'], {'input': input_data})
            encoded = outputs[0]
            
            distance = np.sum((encoded - self.center) ** 2, axis=1)
            anomaly_score = float(distance[0])
            
            is_fall = anomaly_score >= self.threshold
            
            return anomaly_score, is_fall
            
        except Exception:
            return 0.0, False

class V2PersonDetector:
    def __init__(self, yolo_model_path="models/yolov10x.pt"):
        self.yolo_model = YOLO(yolo_model_path)
        self.conf_thresh = 0.6

    def detect_persons(self, frame):
        results = self.yolo_model.track(
            source=[frame],
            stream=False,
            tracker="bytetrack.yaml",
            conf=self.conf_thresh,
            classes=[0],  # Person class
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

def get_risk_level_v2(person_count, is_fall):
    if is_fall:
        return "red"
    elif person_count == 1:
        return "yellow"
    elif person_count == 0:
        return "normal"  # No person detected
    else:
        return "normal"  # Multiple persons

def detect_v2_fall_only_onnx(frame, state: V2ONNXFallDetectionState, fall_detector: V2ONNXFallDetector,
                            config, camera=None, threshold=None):
    threshold = fall_detector.threshold
    
    if camera is not None:
        camera_id = camera.id
        camera_name = camera.name
    else:
        camera_id = "Unknown"
        camera_name = "Unknown Camera"

    resized, gray = preprocess_frame_v2(frame, state.target_size)
    flow_img = compute_optical_flow_v2(state.previous_gray, gray, state.target_size)
    
    if state.previous_gray is not None:
        flow = cv2.calcOpticalFlowFarneback(
            state.previous_gray, gray, None, 
            0.5, 3, 15, 3, 5, 1.2, 0
        )
        mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        avg_mag = mag.mean()
    else:
        avg_mag = 0.0

    keypoints = extract_pose_v2(resized, state.pose_estimator, avg_mag)
    state.previous_gray = gray
    state.optical_flow_queue.append(flow_img)
    state.pose_queue.append(keypoints)
    state.frame_buffer.append(frame)

    if not state.is_ready():
        state.update_last("Analyzing...", 0.0, False)
        return False, 0.0, "Analyzing...", frame

    recent_frames = list(state.frame_buffer)[-4:]
    pose_sequence = list(state.pose_queue)

    import time
    start_time = time.time()
    probability, is_fall = fall_detector.predict(recent_frames, pose_sequence)
    inference_time = (time.time() - start_time) * 1000
    
    detected = is_fall
    label = "fall" if detected else "no_fall"

    state.update_last(label, probability, detected)
    return detected, probability, label, frame

def detect_v2_alone_only_onnx(frame, state: V2AloneFallDetectionState, 
                                 fall_detector: V2ONNXFallDetector, 
                                 person_detector: V2PersonDetector, 
                                 config, camera=None, threshold=None):
    threshold = fall_detector.threshold

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

    resized, gray = preprocess_frame_v2(frame, state.fall_state.target_size)
    flow_img = compute_optical_flow_v2(state.fall_state.previous_gray, gray, state.fall_state.target_size)

    if state.fall_state.previous_gray is not None:
        flow = cv2.calcOpticalFlowFarneback(
            state.fall_state.previous_gray, gray, None, 
            0.5, 3, 15, 3, 5, 1.2, 0
        )
        mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        avg_mag = mag.mean()
    else:
        avg_mag = 0.0

    keypoints = extract_pose_v2(resized, state.fall_state.pose_estimator, avg_mag)
    state.fall_state.previous_gray = gray
    state.fall_state.optical_flow_queue.append(flow_img)
    state.fall_state.pose_queue.append(keypoints)
    state.fall_state.frame_buffer.append(frame)

    if state.fall_state.is_ready():
        recent_frames = list(state.fall_state.frame_buffer)[-4:]
        pose_sequence = list(state.fall_state.pose_queue)

        fall_probability, is_fall = fall_detector.predict(recent_frames, pose_sequence)
        fall_detected = is_fall
        
        pass

    # Determine risk level and detection result
    risk_level = get_risk_level_v2(person_count, fall_detected)
    
    current_time = time.time()
    alone_cooldown = 0
    should_alert_alone = False

    if person_count == 1 and not fall_detected:
        if current_time - state.last_alone_alert_time >= alone_cooldown:
            should_alert_alone = True
            state.last_alone_alert_time = current_time

    if fall_detected:
        detection_result = "fall"
    elif person_count == 1:
        detection_result = "alone"
    elif person_count == 0:
        detection_result = "no_person"
    else:
        detection_result = "normal"

    # Update state
    state.last_person_count = person_count
    state.last_alone_status = risk_level
    state.last_fall_detected = fall_detected
    state.last_fall_probability = fall_probability

    return risk_level, person_count, fall_detected, fall_probability, detection_result, frame, should_alert_alone

def detect_v2_alone_only_onnx(frame, person_detector: V2PersonDetector):
    import time
    start_time = time.time()
    person_count, detections = person_detector.detect_persons(frame)
    detection_time = (time.time() - start_time) * 1000  # Convert to ms
    
    if person_count == 1:
        detection_result = "alone"
        risk_level = "yellow"
    elif person_count == 0:
        detection_result = "no_person"
        risk_level = "normal"
    else:
        detection_result = "normal"
        risk_level = "normal"
    
    pass
    
    return risk_level, person_count, detection_result, frame