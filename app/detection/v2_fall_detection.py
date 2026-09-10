import numpy as np
import cv2
import torch
import torch.nn as nn
import json
from collections import deque, defaultdict
from datetime import datetime, time as dtime
from dataclasses import dataclass
from typing import Deque, Tuple, Dict, Optional
from ultralytics import YOLO
import mediapipe as mp
import time
import os

@dataclass
class TrackState:
    history: Deque[Tuple[int, float, float]]

class V2FallDetectionState:
    """State class for V2 Fall Detection Model"""
    def __init__(self, window_size=16, target_size=(224, 224)):
        self.window_size = window_size
        self.target_size = target_size
        self.optical_flow_queue = deque(maxlen=window_size)
        self.pose_queue = deque(maxlen=window_size)
        self.previous_gray = None
        self.last_label = "Initializing..."
        self.last_probability = 0.0
        self.last_is_fall = False
        self.pose_estimator = mp.solutions.pose.Pose(
            static_image_mode=False, 
            min_detection_confidence=0.5, 
            min_tracking_confidence=0.3
        )

    def is_ready(self):
        return len(self.optical_flow_queue) == self.window_size and len(self.pose_queue) == self.window_size

    def update_last(self, label, probability, is_fall):
        self.last_label = label
        self.last_probability = probability
        self.last_is_fall = is_fall

class V2AloneFallDetectionState:
    """State class for V2 Alone Fall Detection with person tracking"""
    def __init__(self, window_size=16, target_size=(224, 224), history_len=90):
        self.fall_state = V2FallDetectionState(window_size, target_size)
        self.history_len = history_len
        self.states = defaultdict(lambda: TrackState(history=deque(maxlen=history_len)))
        self.frame_id = 0
        self.last_person_count = 0
        self.last_alone_status = "normal"
        self.last_fall_detected = False
        self.last_fall_probability = 0.0
        self.last_alone_alert_time = 0

def preprocess_frame_v2(frame, target_size):
    """Preprocess frame for V2 model"""
    resized = cv2.resize(frame, target_size)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return resized, gray

def compute_optical_flow_v2(prev_gray, curr_gray, target_size):
    """Compute optical flow for V2 model"""
    if prev_gray is None:
        return np.zeros((*target_size[::-1], 3), dtype=np.uint8)
    
    flow = cv2.calcOpticalFlowFarneback(
        prev_gray, curr_gray, None, 
        0.5, 3, 15, 3, 5, 1.2, 0
    )
    mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    
    hsv = np.zeros((*target_size[::-1], 3), dtype=np.uint8)
    hsv[..., 0] = ang * 180 / np.pi / 2
    hsv[..., 1] = 255
    hsv[..., 2] = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX)
    
    flow_img = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    return flow_img

def extract_pose_v2(frame, pose_estimator, flow_magnitude, mag_threshold=0.2):
    """Extract pose keypoints for V2 model"""
    if flow_magnitude < mag_threshold:
        return np.zeros((17, 2), dtype=np.float32)
    
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = pose_estimator.process(rgb)
    keypoints = np.zeros((17, 2), dtype=np.float32)
    
    if results.pose_landmarks:
        for i, lm in enumerate(results.pose_landmarks.landmark[:17]):
            keypoints[i] = [lm.x, lm.y]
    
    return keypoints

def load_normalization_params(normalization_path):
    """Load normalization parameters from config file"""
    try:
        with open(normalization_path, 'r') as f:
            norm_params = json.load(f)
        return norm_params
    except FileNotFoundError:
        # Default normalization parameters - no normalization
        return {}

def extract_features_v2(optical_flow_seq, pose_seq, frames=None):
    """Extract features similar to training process"""
    # Expected feature sizes based on model config:
    # RGB: 2048, Flow: 236, Pose: 136 = Total: 2420
    
    # RGB features from frames (if available)
    if frames is not None and len(frames) > 0:
        try:
            import torchvision.transforms as transforms
            import torchvision.models as models
            from torchvision.models import ResNet50_Weights
            
            # Use ResNet50 for RGB feature extraction (like original inference.py)
            device = torch.device('cpu')  # Use CPU for now
            model = models.resnet50(weights=ResNet50_Weights.DEFAULT)
            model = torch.nn.Sequential(*list(model.children())[:-1])
            model.eval()
            
            transform = transforms.Compose([
                transforms.ToPILImage(),
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
            ])
            
            # Process selected frames (every 4th frame like original)
            selected_frames = frames[::4] if len(frames) > 4 else frames
            tensors = []
            for frame in selected_frames[:4]:  # Limit to 4 frames
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                tensor = transform(frame_rgb)
                tensors.append(tensor)
            
            if tensors:
                batch = torch.stack(tensors)
                with torch.no_grad():
                    features = model(batch)
                    features = features.view(features.size(0), -1)
                    rgb_features = features.mean(dim=0).numpy()
                    
                # Ensure 2048 features
                if len(rgb_features) > 2048:
                    rgb_features = rgb_features[:2048]
                elif len(rgb_features) < 2048:
                    rgb_features = np.pad(rgb_features, (0, 2048 - len(rgb_features)))
            else:
                rgb_features = np.zeros(2048, dtype=np.float32)
                
        except Exception as e:
            print(f"RGB feature extraction failed: {e}, using zeros")
            rgb_features = np.zeros(2048, dtype=np.float32)
    else:
        # Fallback to zeros if no frames
        rgb_features = np.zeros(2048, dtype=np.float32)
    
    # Optical flow features (resize to expected size)
    optical_flow_flat = optical_flow_seq.flatten()
    if len(optical_flow_flat) > 236:
        # Downsample to 236 features
        indices = np.linspace(0, len(optical_flow_flat)-1, 236, dtype=int)
        optical_flow_features = optical_flow_flat[indices]
    else:
        # Pad to 236 features
        optical_flow_features = np.pad(optical_flow_flat, (0, max(0, 236 - len(optical_flow_flat))), 'constant')[:236]
    
    # Pose features (should be 136)
    pose_flat = pose_seq.flatten()
    if len(pose_flat) > 136:
        # Downsample to 136 features
        indices = np.linspace(0, len(pose_flat)-1, 136, dtype=int)
        pose_features = pose_flat[indices]
    else:
        # Pad to 136 features
        pose_features = np.pad(pose_flat, (0, max(0, 136 - len(pose_flat))), 'constant')[:136]
    
    # Combine features: RGB (2048) + Flow (236) + Pose (136) = 2420
    combined_features = np.concatenate([rgb_features, optical_flow_features, pose_features])
    
    return combined_features

def normalize_features(features, norm_params):
    """Normalize features using training statistics"""
    if "mean" in norm_params and "std" in norm_params:
        mean = np.array(norm_params["mean"])
        std = np.array(norm_params["std"])
        
        # Ensure feature vector matches expected length
        if len(features) == len(mean):
            features = (features - mean) / std
        else:
            print(f"Warning: Feature length mismatch. Expected {len(mean)}, got {len(features)}")
    
    return features

class V2FallPyTorchDetector:
    """PyTorch-based V2 Fall Detection Model (DeepSVDD)"""
    def __init__(self, model_path, config_path=None, normalization_path=None, threshold_path=None):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # Load model
        checkpoint = torch.load(model_path, map_location=self.device)
        
        # Handle different checkpoint formats
        if isinstance(checkpoint, dict):
            if 'model_state_dict' in checkpoint:
                # Create model architecture and load state dict
                self.model = self.create_model_architecture(config_path)
                
                state_dict = checkpoint['model_state_dict']
                
                # Handle encoder prefix in state dict keys - need to ADD prefix, not remove
                if not any(key.startswith('encoder.') for key in state_dict.keys()):
                    # Add encoder prefix if missing
                    new_state_dict = {}
                    for key, value in state_dict.items():
                        if key in ['0.weight', '0.bias', '3.weight', '3.bias', '6.weight', '6.bias']:
                            new_key = f'encoder.{key}'
                            new_state_dict[new_key] = value
                        else:
                            new_state_dict[key] = value
                    state_dict = new_state_dict
                
                self.model.load_state_dict(state_dict)
                
                # Load DeepSVDD center if available
                self.center = checkpoint.get('center', None)
                if self.center is not None:
                    self.center = self.center.to(self.device)
                
            elif 'state_dict' in checkpoint:
                self.model = self.create_model_architecture(config_path)
                self.model.load_state_dict(checkpoint['state_dict'])
                self.center = checkpoint.get('center', None)
            else:
                # Assume the dict is the state dict itself
                self.model = self.create_model_architecture(config_path)
                self.model.load_state_dict(checkpoint)
                self.center = None
        else:
            # Model object saved directly
            self.model = checkpoint
            self.center = None
        
        self.model.to(self.device)
        self.model.eval()
        
        # Load configuration
        self.config = self.load_config(config_path)
        
        # Load normalization parameters
        self.norm_params = load_normalization_params(normalization_path) if normalization_path else {}
        
        # Load threshold
        self.threshold = self.load_threshold(threshold_path)
        
        print(f"V2 Fall Detection Model loaded on {self.device}")
        print(f"Model threshold: {self.threshold}")

    def create_model_architecture(self, config_path):
        """Create DeepSVDD model architecture exactly like original"""
        # Use exact same architecture as inference.py
        class DeepSVDDEncoder(torch.nn.Module):
            def __init__(self, input_dim=2420):
                super().__init__()
                self.encoder = torch.nn.Sequential(
                    torch.nn.Linear(input_dim, 512),
                    torch.nn.ReLU(),
                    torch.nn.Dropout(0.1),
                    torch.nn.Linear(512, 256),
                    torch.nn.ReLU(),
                    torch.nn.Dropout(0.1),
                    torch.nn.Linear(256, 128)
                )
            
            def forward(self, x):
                return self.encoder(x)
        
        return DeepSVDDEncoder()

    def load_config(self, config_path):
        """Load model configuration"""
        if config_path and os.path.exists(config_path):
            with open(config_path, 'r') as f:
                return json.load(f)
        return {}

    def load_threshold(self, threshold_path):
        """Load optimal threshold from training"""
        if threshold_path and os.path.exists(threshold_path):
            with open(threshold_path, 'r') as f:
                threshold_data = json.load(f)
                return threshold_data.get('threshold', 0.5)  # Use 'threshold' key based on actual file
        return 0.5

    def predict(self, optical_flow_seq, pose_seq, frames=None):
        """Make prediction using V2 DeepSVDD model"""
        try:
            # Extract and combine features (similar to training process)
            # Include frames for RGB feature extraction
            combined_features = extract_features_v2(optical_flow_seq, pose_seq, frames=frames)
            
            # Normalize features
            if self.norm_params:
                combined_features = normalize_features(combined_features, self.norm_params)
            
            # Convert to tensor
            feature_tensor = torch.from_numpy(combined_features).float().unsqueeze(0)
            feature_tensor = feature_tensor.to(self.device)
            
            # Inference
            with torch.no_grad():
                # DeepSVDD model forward pass
                outputs = self.model(feature_tensor)
                
                # Calculate distance from center (DeepSVDD anomaly score)
                if self.center is not None:
                    # Distance from DeepSVDD center
                    anomaly_score = torch.norm(outputs - self.center, p=2, dim=1)
                    anomaly_score = anomaly_score.cpu().numpy()[0]
                else:
                    # Fallback: use raw output as score
                    if isinstance(outputs, torch.Tensor):
                        anomaly_score = torch.norm(outputs, p=2, dim=1).cpu().numpy()[0]
                    else:
                        anomaly_score = float(outputs)
                
                # Higher anomaly score means more likely to be fall
                is_fall = anomaly_score > self.threshold
                
                # Convert anomaly score to probability-like value (normalize)
                probability = float(anomaly_score)
                
                return probability, is_fall
                
        except Exception as e:
            print(f"Error during V2 model prediction: {e}")
            import traceback
            traceback.print_exc()
            return 0.0, False

class V2PersonDetector:
    """Person detection for V2 model using YOLO"""
    def __init__(self, yolo_model_path="models/yolov10x.pt"):
        self.yolo_model = YOLO(yolo_model_path)
        self.conf_thresh = 0.6

    def detect_persons(self, frame):
        """Detect persons in frame"""
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
    """Determine risk level for V2 model"""
    if is_fall:
        return "red"  # Fall detected - highest priority
    elif person_count == 1:
        return "yellow"  # Alone but no fall
    elif person_count == 0:
        return "normal"  # No person detected
    else:
        return "normal"  # Multiple persons

def detect_v2_fall_only(frame, state: V2FallDetectionState, fall_detector: V2FallPyTorchDetector, 
                       config, camera=None, threshold=None):
    """V2 Fall detection only (legacy mode)"""
    if camera is not None:
        threshold = camera.ai_confidence_threshold
    else:
        threshold = threshold if threshold is not None else config.get("AI_CONFIDENCE_THRESHOLD", 0.5)

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

    if not state.is_ready():
        state.update_last("Analyzing...", 0.0, False)
        return False, 0.0, "Analyzing...", frame

    # Prepare inputs for model
    optical_flow_array = np.stack(state.optical_flow_queue)
    optical_flow_tensor = optical_flow_array.transpose(0, 3, 1, 2)
    optical_flow_tensor = np.expand_dims(optical_flow_tensor, 0)
    optical_flow_tensor = optical_flow_tensor.astype(np.float32) / 255.0

    pose_array = np.stack(state.pose_queue)
    pose_tensor = np.expand_dims(pose_array, 0)
    pose_tensor = pose_tensor.astype(np.float32)

    # Get recent frames for RGB feature extraction
    recent_frames = []
    if hasattr(state, 'frame_buffer'):
        recent_frames = list(state.frame_buffer)[-4:]  # Last 4 frames
    else:
        # Initialize frame buffer if not exists
        if not hasattr(state, 'frame_buffer'):
            state.frame_buffer = deque(maxlen=16)
        state.frame_buffer.append(frame)
        recent_frames = [frame] * 4  # Use current frame 4 times if no history

    # Make prediction with frames for RGB extraction
    probability, is_fall = fall_detector.predict(optical_flow_tensor, pose_tensor, frames=recent_frames)
    detected = is_fall and probability > threshold
    label = "fall" if detected else "no_fall"

    state.update_last(label, probability, detected)
    return detected, probability, label, frame

def detect_v2_alone_and_fall(frame, state: V2AloneFallDetectionState, 
                           fall_detector: V2FallPyTorchDetector, 
                           person_detector: V2PersonDetector, 
                           config, camera=None, threshold=None):
    """V2 Combined alone and fall detection"""
    if camera is not None:
        threshold = camera.ai_confidence_threshold
    else:
        threshold = threshold if threshold is not None else config.get("AI_CONFIDENCE_THRESHOLD", 0.5)

    state.frame_id += 1
    
    # Person detection
    person_count, detections = person_detector.detect_persons(frame)
    
    # Update tracking states
    for detection in detections:
        tid = detection['track_id']
        x1, y1, x2, y2 = detection['bbox']
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        
        if tid != -1:
            track_state = state.states[tid]
            track_state.history.append((state.frame_id, cx, cy))

    # Fall detection processing
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

    if state.fall_state.is_ready():
        optical_flow_array = np.stack(state.fall_state.optical_flow_queue)
        optical_flow_tensor = optical_flow_array.transpose(0, 3, 1, 2)
        optical_flow_tensor = np.expand_dims(optical_flow_tensor, 0)
        optical_flow_tensor = optical_flow_tensor.astype(np.float32) / 255.0

        pose_array = np.stack(state.fall_state.pose_queue)
        pose_tensor = np.expand_dims(pose_array, 0)
        pose_tensor = pose_tensor.astype(np.float32)

        # Get recent frames for RGB feature extraction
        recent_frames = []
        if hasattr(state, 'frame_buffer'):
            recent_frames = list(state.frame_buffer)[-4:]  # Last 4 frames
        else:
            # Initialize frame buffer if not exists
            if not hasattr(state, 'frame_buffer'):
                state.frame_buffer = deque(maxlen=16)
            state.frame_buffer.append(frame)
            recent_frames = [frame] * 4  # Use current frame 4 times if no history

        fall_probability, is_fall = fall_detector.predict(optical_flow_tensor, pose_tensor, frames=recent_frames)
        fall_detected = is_fall and fall_probability > threshold

    # Determine risk level and detection result
    risk_level = get_risk_level_v2(person_count, fall_detected)
    
    current_time = time.time()
    alone_cooldown = 0
    should_alert_alone = False

    if person_count == 1 and not fall_detected:
        # Check if enough time has passed since last alone alert
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

def detect_v2_alone_only(frame, person_detector: V2PersonDetector):
    """V2 Simplified alone detection without fall processing"""
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