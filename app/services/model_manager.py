import os
import threading
from app.config import Config
from app.detection.v2_fall_detection_onnx import V2ONNXFallDetector, V2PersonDetector

class ModelManager:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(ModelManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            with ModelManager._lock:
                if not self._initialized:
                    self.v2_fall_detector = None
                    self.v2_person_detector = None
                    self._fall_detector_loading = False
                    self._person_detector_loading = False
                    self._initialized = True
                    print("[Model Manager] Initialized - Models will load on first use")
    
    def _load_fall_detector(self):
        """Load V2 ONNX Fall Detector (lazy loading with thread safety)"""
        if self.v2_fall_detector is not None:
            return
            
        with ModelManager._lock:
            # Double-check after acquiring lock
            if self.v2_fall_detector is not None:
                return
                
            if self._fall_detector_loading:
                print("[Model Manager] Fall detector already loading, skipping...")
                return
                
            try:
                self._fall_detector_loading = True
                print("[Model Manager] Loading V2 ONNX Fall Detector...")
                self.v2_fall_detector = V2ONNXFallDetector(
                    model_dir=Config.V2_FALL_DETECTION_MODEL_DIR
                )
                print("[Model Manager] V2 ONNX Fall Detector loaded successfully!")
            except Exception as e:
                print(f"[Model Manager] Error loading fall detector: {e}")
                self.v2_fall_detector = None
            finally:
                self._fall_detector_loading = False
    
    def _load_person_detector(self):
        """Load V2 Person Detector (YOLO) (lazy loading with thread safety)"""
        if self.v2_person_detector is not None:
            return
            
        with ModelManager._lock:
            # Double-check after acquiring lock
            if self.v2_person_detector is not None:
                return
                
            if self._person_detector_loading:
                print("[Model Manager] Person detector already loading, skipping...")
                return
                
            try:
                self._person_detector_loading = True
                print("[Model Manager] Loading V2 Person Detector (YOLO)...")
                yolo_path = "/app/models/yolov10x.pt"
                self.v2_person_detector = V2PersonDetector(yolo_path)
                print("[Model Manager] V2 Person Detector loaded successfully!")
            except Exception as e:
                print(f"[Model Manager] Error loading person detector: {e}")
                self.v2_person_detector = None
            finally:
                self._person_detector_loading = False
    
    def get_v2_fall_detector(self):
        """Get V2 fall detector, loading if necessary"""
        if self.v2_fall_detector is None:
            self._load_fall_detector()
        return self.v2_fall_detector
    
    def get_v2_person_detector(self):
        """Get V2 person detector, loading if necessary"""
        if self.v2_person_detector is None:
            self._load_person_detector()
        return self.v2_person_detector
    
    def is_ready(self):
        return (self.v2_fall_detector is not None and 
                self.v2_person_detector is not None)
    
    def get_model_info(self):
        return {
            "v2_fall_detector_loaded": self.v2_fall_detector is not None,
            "v2_person_detector_loaded": self.v2_person_detector is not None,
            "models_ready": self.is_ready()
        }

model_manager = ModelManager()