from app import celery
from app.detection.bed_exit import detect_bed_exit, BedExitDetectionState
from app.detection.fall_detection import (
    detect_fall_legacy, FallDetectionState, FallONNXDetector, AlonePersonDetector, detect_alone_only
)
from app.services.logging_service import save_detection_log, save_system_log
from app.services.telegram_service import send_telegram_message_async
from app.services.alert_service import save_alert_log
from app.models.camera import Camera
from app import db
import cv2
import time
import traceback
from datetime import datetime
import os
import tempfile
import pytz
from datetime import time as dtime
import threading
import queue
from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Deque, Tuple, Dict
tz = pytz.timezone('Asia/Bangkok')
from app.config import Config

@dataclass
class TrackState:
    history: Deque[Tuple[int, float, float]]

class AloneDetectionState:
    def __init__(self, history_len=90):
        self.history_len = history_len
        self.states = defaultdict(lambda: TrackState(history=deque(maxlen=history_len)))
        self.frame_id = 0
        self.last_person_count = 0
        self.last_alone_status = "normal"
        self.last_alone_alert_time = 0

def detect_alone_with_state(frame, state: AloneDetectionState, person_detector: AlonePersonDetector):
    state.frame_id += 1
    
    risk_level, person_count, detection_result, processed_frame = detect_alone_only(frame, person_detector)
    
    person_count_internal, detections = person_detector.detect_persons(frame)
    
    for detection in detections:
        tid = detection['track_id']
        x1, y1, x2, y2 = detection['bbox']
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        
        if tid != -1:
            track_state = state.states[tid]
            track_state.history.append((state.frame_id, cx, cy))
    
    current_time = time.time()
    alone_cooldown = 300  # 5 minutes cooldown for alone detection
    should_alert_alone = False
    
    if person_count == 1:
        # Check if enough time has passed since last alone alert
        if current_time - state.last_alone_alert_time >= alone_cooldown:
            should_alert_alone = True
            state.last_alone_alert_time = current_time
    
    state.last_person_count = person_count
    state.last_alone_status = risk_level
    
    return risk_level, person_count, detection_result, processed_frame, should_alert_alone

@celery.task
def process_fall_detection(camera_id, config):
    from app import create_app
    app = create_app()
    with app.app_context():
        try:
            camera = Camera.query.get(camera_id)
            if not camera or not camera.is_active:
                save_system_log('WARNING', f'Fall detection: Camera {camera_id} not found or inactive', 'DETECTION')
                return
            
            save_system_log('INFO', f'Fall detection started for camera {camera.name}', 'DETECTION', camera.user_id)
            
            # Setup camera stream
            original_url = camera.url
            if camera.url.startswith('http://localhost:3000/videos/'):
                filename = camera.url.split('/')[-1]
                camera.url = f"/app/videos/{filename}"
            elif '\\' in camera.url and 'videos' in camera.url:
                filename = camera.url.split('\\')[-1]
                camera.url = f"/app/videos/{filename}"
            elif 'videos/' in camera.url and not camera.url.startswith('/app/videos/'):
                filename = camera.url.split('/')[-1]
                camera.url = f"/app/videos/{filename}"
            
            is_video_file = not camera.url.startswith(('rtsp', 'rtmp')) and ('.' in camera.url or 'localhost' in original_url)
            
            cap = cv2.VideoCapture(camera.url)
            if not cap.isOpened():
                save_system_log('ERROR', f'Fall detection: Failed to open camera URL: {camera.url}', 'DETECTION', camera.user_id)
                return
            
            if is_video_file:
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                if fps <= 0:
                    fps = 30
            
            # Initialize fall detection
            state = FallDetectionState()
            model_path = config["FALL_DETECTION_MODEL_PATH"]
            detector = FallONNXDetector(model_path)
            
            last_log_time = 0
            last_detection_result = None
            log_interval = config["LOGGING_INTERVAL"]
            loop_count = 0
            frame_skip_count = 0
            max_retries = 5
            
            while camera.is_active:
                ret, frame = cap.read()
                if not ret:
                    if is_video_file:
                        current_frame = cap.get(cv2.CAP_PROP_POS_FRAMES)
                        if current_frame >= total_frames - 1 or current_frame == 0:
                            loop_count += 1
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            ret, frame = cap.read()
                            if not ret:
                                frame_skip_count += 1
                                if frame_skip_count >= max_retries:
                                    break
                                time.sleep(1)
                                continue
                            else:
                                frame_skip_count = 0
                        else:
                            frame_skip_count += 1
                            if frame_skip_count >= max_retries:
                                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                                frame_skip_count = 0
                                continue
                            time.sleep(0.1)
                            continue
                    else:
                        time.sleep(1)
                        continue
                
                frame_skip_count = 0
                threshold = camera.ai_confidence_threshold
                
                # Fall detection
                detected, confidence, label, img = detect_fall_legacy(
                    frame, state, detector, config, camera=camera, threshold=threshold
                )
                
                # Logging
                now = time.time()
                if now - last_log_time >= log_interval:
                    if last_detection_result != label or label not in ['no_fall', 'normal']:
                        save_detection_log(camera_id, label, confidence)
                        print(f"[Camera {camera_id}] Fall Detection: {label}, Confidence: {confidence:.2f}")
                        last_detection_result = label
                    last_log_time = now
                
                # Alert handling
                if not hasattr(camera, '_last_fall_alert_time'):
                    camera._last_fall_alert_time = 0
                
                notification_cooldown = camera.notification_cooldown
                
                def parse_time(timestr):
                    h, m = map(int, timestr.split(':'))
                    return dtime(h, m)
                    
                now_time = datetime.now(tz).time()
                start_time = parse_time(camera.alert_start_time)
                end_time = parse_time(camera.alert_end_time)
                in_time_window = False
                if start_time < end_time:
                    in_time_window = start_time <= now_time < end_time
                else:
                    in_time_window = now_time >= start_time or now_time < end_time
                
                if detected and in_time_window and (now - camera._last_fall_alert_time > notification_cooldown):
                    alert_dir = getattr(Config, 'ALERT_IMAGE_DIR', None) or '/app/tmp'
                    os.makedirs(alert_dir, exist_ok=True)
                    img_path = os.path.join(alert_dir, f"fall_detect_{camera_id}_{int(time.time())}.jpg")
                    cv2.imwrite(img_path, img)
                    
                    save_alert_log(camera_id, "fall_red", img_path, f"Confidence: {confidence:.2f}")
                    
                    send_telegram_message_async(
                        camera_id, camera.name, camera.room_name, "fall_red", datetime.now(tz).isoformat(), img_path
                    )
                    
                    print(f"[Camera {camera_id}] FALL ALERT: {label}, Confidence: {confidence:.2f}")
                    camera._last_fall_alert_time = now
                
                db.session.refresh(camera)
                if not camera.is_active:
                    break
                
                if is_video_file and fps > 0:
                    time.sleep(1.0 / fps)
            
            cap.release()
            save_system_log('INFO', f'Fall detection session ended for camera {camera.name}', 'DETECTION', camera.user_id)
            
        except Exception as e:
            save_system_log('ERROR', f'Fall detection error for {camera_id}: {str(e)}', 'DETECTION')
            if 'cap' in locals():
                cap.release()
            raise

@celery.task
def process_alone_detection(camera_id, config):
    from app import create_app
    app = create_app()
    with app.app_context():
        try:
            camera = Camera.query.get(camera_id)
            if not camera or not camera.is_active:
                save_system_log('WARNING', f'Alone detection: Camera {camera_id} not found or inactive', 'DETECTION')
                return
            
            save_system_log('INFO', f'Alone detection started for camera {camera.name}', 'DETECTION', camera.user_id)
            
            # Setup camera stream
            original_url = camera.url
            if camera.url.startswith('http://localhost:3000/videos/'):
                filename = camera.url.split('/')[-1]
                camera.url = f"/app/videos/{filename}"
            elif '\\' in camera.url and 'videos' in camera.url:
                filename = camera.url.split('\\')[-1]
                camera.url = f"/app/videos/{filename}"
            elif 'videos/' in camera.url and not camera.url.startswith('/app/videos/'):
                filename = camera.url.split('/')[-1]
                camera.url = f"/app/videos/{filename}"
            
            is_video_file = not camera.url.startswith(('rtsp', 'rtmp')) and ('.' in camera.url or 'localhost' in original_url)
            
            cap = cv2.VideoCapture(camera.url)
            if not cap.isOpened():
                save_system_log('ERROR', f'Alone detection: Failed to open camera URL: {camera.url}', 'DETECTION', camera.user_id)
                return
            
            if is_video_file:
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                if fps <= 0:
                    fps = 30
            
            # Initialize alone detection
            state = AloneDetectionState()
            person_detector = AlonePersonDetector()
            
            last_log_time = 0
            last_detection_result = None
            last_risk_level = None
            log_interval = config["LOGGING_INTERVAL"]
            loop_count = 0
            frame_skip_count = 0
            max_retries = 5
            
            while camera.is_active:
                ret, frame = cap.read()
                if not ret:
                    if is_video_file:
                        current_frame = cap.get(cv2.CAP_PROP_POS_FRAMES)
                        if current_frame >= total_frames - 1 or current_frame == 0:
                            loop_count += 1
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            ret, frame = cap.read()
                            if not ret:
                                frame_skip_count += 1
                                if frame_skip_count >= max_retries:
                                    break
                                time.sleep(1)
                                continue
                            else:
                                frame_skip_count = 0
                        else:
                            frame_skip_count += 1
                            if frame_skip_count >= max_retries:
                                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                                frame_skip_count = 0
                                continue
                            time.sleep(0.1)
                            continue
                    else:
                        time.sleep(1)
                        continue
                
                frame_skip_count = 0
                
                # Alone detection
                risk_level, person_count, detection_result, img, should_alert_alone = detect_alone_with_state(
                    frame, state, person_detector
                )
                
                # Logging
                now = time.time()
                if now - last_log_time >= log_interval:
                    if (last_detection_result != detection_result or last_risk_level != risk_level or 
                        detection_result not in ['normal', 'no_person'] or risk_level != 'normal'):
                        save_detection_log(camera_id, detection_result, 0.8, risk_level, person_count)
                        print(f"[Camera {camera_id}] Alone Detection: {detection_result}, Risk: {risk_level}, Persons: {person_count}")
                        last_detection_result = detection_result
                        last_risk_level = risk_level
                    last_log_time = now
                
                # Alert handling - Skip telegram notification for yellow alerts (alone detection)
                if not hasattr(camera, '_last_alone_alert_time'):
                    camera._last_alone_alert_time = 0
                
                notification_cooldown = camera.notification_cooldown
                
                def parse_time(timestr):
                    h, m = map(int, timestr.split(':'))
                    return dtime(h, m)
                    
                now_time = datetime.now(tz).time()
                start_time = parse_time(camera.alert_start_time)
                end_time = parse_time(camera.alert_end_time)
                in_time_window = False
                if start_time < end_time:
                    in_time_window = start_time <= now_time < end_time
                else:
                    in_time_window = now_time >= start_time or now_time < end_time
                
                if should_alert_alone and in_time_window and (now - camera._last_alone_alert_time > notification_cooldown):
                    print(f"[Camera {camera_id}] ALONE DETECTED (No notification sent): {detection_result}, Risk: {risk_level}")
                    camera._last_alone_alert_time = now
                
                db.session.refresh(camera)
                if not camera.is_active:
                    break
                
                if is_video_file and fps > 0:
                    time.sleep(1.0 / fps)
            
            cap.release()
            save_system_log('INFO', f'Alone detection session ended for camera {camera.name}', 'DETECTION', camera.user_id)
            
        except Exception as e:
            save_system_log('ERROR', f'Alone detection error for {camera_id}: {str(e)}', 'DETECTION')
            if 'cap' in locals():
                cap.release()
            raise
@celery.task
def process_bed_exit_detection(camera_id, config):
    from app import create_app
    app = create_app()
    with app.app_context():
        try:
            camera = Camera.query.get(camera_id)
            if not camera or not camera.is_active:
                save_system_log('WARNING', f'Bed exit detection: Camera {camera_id} not found or inactive', 'DETECTION')
                return
            
            save_system_log('INFO', f'Bed exit detection started for camera {camera.name}', 'DETECTION', camera.user_id)
            
            # Setup camera stream
            original_url = camera.url
            if camera.url.startswith('http://localhost:3000/videos/'):
                filename = camera.url.split('/')[-1]
                camera.url = f"/app/videos/{filename}"
            elif '\\' in camera.url and 'videos' in camera.url:
                filename = camera.url.split('\\')[-1]
                camera.url = f"/app/videos/{filename}"
            elif 'videos/' in camera.url and not camera.url.startswith('/app/videos/'):
                filename = camera.url.split('/')[-1]
                camera.url = f"/app/videos/{filename}"
            
            is_video_file = not camera.url.startswith(('rtsp', 'rtmp')) and ('.' in camera.url or 'localhost' in original_url)
            
            cap = cv2.VideoCapture(camera.url)
            if not cap.isOpened():
                save_system_log('ERROR', f'Bed exit detection: Failed to open camera URL: {camera.url}', 'DETECTION', camera.user_id)
                return
            
            if is_video_file:
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                if fps <= 0:
                    fps = 30
            
            # Initialize bed exit detection
            state = BedExitDetectionState()
            
            last_log_time = 0
            last_detection_result = None
            log_interval = config["LOGGING_INTERVAL"]
            loop_count = 0
            frame_skip_count = 0
            max_retries = 5
            
            while camera.is_active:
                ret, frame = cap.read()
                if not ret:
                    if is_video_file:
                        current_frame = cap.get(cv2.CAP_PROP_POS_FRAMES)
                        if current_frame >= total_frames - 1 or current_frame == 0:
                            loop_count += 1
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            ret, frame = cap.read()
                            if not ret:
                                frame_skip_count += 1
                                if frame_skip_count >= max_retries:
                                    break
                                time.sleep(1)
                                continue
                            else:
                                frame_skip_count = 0
                        else:
                            frame_skip_count += 1
                            if frame_skip_count >= max_retries:
                                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                                frame_skip_count = 0
                                continue
                            time.sleep(0.1)
                            continue
                    else:
                        time.sleep(1)
                        continue
                
                frame_skip_count = 0
                threshold = camera.ai_confidence_threshold
                
                # Bed exit detection
                result = detect_bed_exit(
                    frame, state, config, camera=camera, threshold=threshold
                )
                
                detected = False
                confidence = 0.0
                label = "no_detection"
                img = frame
                
                if result is not None:
                    detected, confidence, label, img = result
                
                # Logging
                now = time.time()
                if now - last_log_time >= log_interval:
                    if last_detection_result != label or label not in ['no_detection', 'normal']:
                        save_detection_log(camera_id, label, confidence)
                        print(f"[Camera {camera_id}] Bed Exit Detection: {label}, Confidence: {confidence:.2f}")
                        last_detection_result = label
                    last_log_time = now
                
                # Alert handling
                if not hasattr(camera, '_last_bed_alert_time'):
                    camera._last_bed_alert_time = 0
                
                notification_cooldown = camera.notification_cooldown
                
                def parse_time(timestr):
                    h, m = map(int, timestr.split(':'))
                    return dtime(h, m)
                    
                now_time = datetime.now(tz).time()
                start_time = parse_time(camera.alert_start_time)
                end_time = parse_time(camera.alert_end_time)
                in_time_window = False
                if start_time < end_time:
                    in_time_window = start_time <= now_time < end_time
                else:
                    in_time_window = now_time >= start_time or now_time < end_time
                
                if detected and in_time_window and (now - camera._last_bed_alert_time > notification_cooldown):
                    img_path = f"/app/tmp/bed_exit_detect_{camera_id}_{int(time.time())}.jpg"
                    os.makedirs(os.path.dirname(img_path), exist_ok=True)
                    cv2.imwrite(img_path, img)
                    
                    save_alert_log(camera_id, "bed_exit", img_path, f"Confidence: {confidence:.2f}")
                    
                    send_telegram_message_async(
                        camera_id, camera.name, camera.room_name, "bed_exit", datetime.now(tz).isoformat(), img_path
                    )
                    
                    print(f"[Camera {camera_id}] BED EXIT ALERT: {label}, Confidence: {confidence:.2f}")
                    camera._last_bed_alert_time = now
                
                db.session.refresh(camera)
                if not camera.is_active:
                    break
                
                if is_video_file and fps > 0:
                    time.sleep(1.0 / fps)
            
            cap.release()
            save_system_log('INFO', f'Bed exit detection session ended for camera {camera.name}', 'DETECTION', camera.user_id)
            
        except Exception as e:
            save_system_log('ERROR', f'Bed exit detection error for {camera_id}: {str(e)}', 'DETECTION')
            if 'cap' in locals():
                cap.release()
            raise

# V2 Fall Detection Tasks

class V3FallRunner:
    """Frame sampling and per-person state of the v3 fall detector, for ONE video source.

    No database and no alerts live here, on purpose: the Celery loop below and the offline
    evaluation (tools/v3_eval_via_camera_manager.py) both drive this class, so the behaviour that
    was measured and the behaviour that is deployed are the same code.

    Why the sampling is here. The classifier's window is a fixed number of FRAMES, so how much
    real time it covers depends on the rate frames reach it. The detector was evaluated at
    V3_TARGET_FPS (8). A live camera hands back its newest frame, so waiting for the next slot
    and then reading is enough. A FILE does not drop frames: it must be sampled by SOURCE time
    (frame index = round(n * source_fps / target_fps)), otherwise a 24 fps clip is classified at
    8 fps of 'next frame' and its window spans three times the motion it was tuned for.
    target_fps = 0 disables the cap and every frame is classified.
    """

    def __init__(self, fall_detector, src_fps, is_video_file, target_fps=None, realtime=True):
        from app.detection.v3_fall_detection import (
            V3MultiPersonFallState, detect_v3_fall_multi, alert_result)
        self._new_state = V3MultiPersonFallState
        self._detect = detect_v3_fall_multi
        self._alert_result = alert_result
        self.detector = fall_detector
        self.src_fps = src_fps if src_fps and src_fps > 0 else 0.0
        self.is_video_file = is_video_file
        if target_fps is None:
            target_fps = float(os.environ.get('V3_TARGET_FPS', 0))
        self.target_fps = target_fps
        self.min_period = 1.0 / target_fps if target_fps > 0 else 0.0
        self.realtime = realtime      # False: no waiting (offline evaluation); frames are identical
        self.reset()

    def reset(self):
        """Forget every track, window, crop box and file position. Call at the start of a source,
        when a file loops back to frame 0, and after a gap that makes old tracks meaningless."""
        self.state = self._new_state()
        self.detector.reset_roi_state()
        self.source_index = 0     # where the decoder is in the file
        self.source_pos = 0       # frames classified so far
        self.next_due = 0.0

    def read(self, cap):
        """-> (ok, frame, source_index): the next frame to classify."""
        if self.realtime and self.min_period:
            wait = self.next_due - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        if self.is_video_file and self.min_period and self.src_fps > 0:
            want = int(round(self.source_pos * self.src_fps / self.target_fps))
            while self.source_index < want and cap.grab():
                self.source_index += 1
        ok, frame = cap.read()
        index = self.source_index
        if ok:
            self.source_index += 1
            self.source_pos += 1
            # Scheduled from now, so a stall does not leave a backlog of 'due' frames
            self.next_due = time.monotonic() + self.min_period
        return ok, frame, index

    def step(self, frame):
        """-> (results, top). results: one (track_id, detected, prob, label, centroid) per tracked
        person; top: the one credited with an alert (alert_result)."""
        results = self._detect(frame, self.state, self.detector, {})
        return results, self._alert_result(results)

    @classmethod
    def iter_video(cls, fall_detector, path, target_fps=None, realtime=False):
        """Offline replay of one file: yields (source_index, source_fps, frame, results, top, runner)."""
        cap = cv2.VideoCapture(path)
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            runner = cls(fall_detector, fps, True, target_fps=target_fps, realtime=realtime)
            while True:
                ok, frame, index = runner.read(cap)
                if not ok:
                    break
                results, top = runner.step(frame)
                yield index, fps, frame, results, top, runner
        finally:
            cap.release()


def notify_fall_alert(camera_id, camera_name, room_name, detection_type, timestamp, image_path, confidence=None):
    """Outbound notification for a v3 fall alert: the one place the channel is plugged in.

    Telegram was removed from this loop (plan A); the LINE sender replaces the body of this function in
    step 4. Until then it only logs, so the alert is visible in the worker log and, through save_alert_log,
    in the web UI. It runs inline in the detection loop: an implementation must not block (the LINE
    sender will hand off to a thread, as the Telegram one did) and may raise, because the caller contains it.
    """
    print(f"[Camera {camera_id}] notify_fall_alert: {detection_type} '{camera_name}' / '{room_name}' "
          f"confidence={confidence} image={image_path} (no channel configured yet)")


def _safe_rollback():
    """Clear a failed transaction so the next query on the shared session can run; never raises."""
    try:
        db.session.rollback()
    except Exception as exc:                                        # noqa: BLE001
        print(f"[V3 Pose] rollback failed: {exc}")


def _raise_v3_fall_alert(camera, frame, probability, label, seen_count):
    """Store and announce one v3 fall alert. Each step is isolated so a failure in one cannot skip the
    next: alert image -> alert row (the web UI shows the event) -> outbound notification.
    Exceptions that escape this function are caught by the loop as well."""
    camera_id, camera_name, room_name = camera.id, camera.name, camera.room_name
    current_time = datetime.now(tz)

    img_path = None
    try:
        alert_dir = getattr(Config, 'ALERT_IMAGE_DIR', None) or '/app/tmp'
        os.makedirs(alert_dir, exist_ok=True)
        path = os.path.join(alert_dir, f"v3_fall_detect_{camera_id}_{int(time.time())}.jpg")
        if cv2.imwrite(path, frame):
            img_path = path
        else:
            print(f"[Camera {camera_id}] V3 alert image could not be written to {path}")
    except Exception:
        print(f"[Camera {camera_id}] V3 alert image failed:\n{traceback.format_exc()}")

    try:
        saved = save_alert_log(camera_id, 'fall_red', img_path,
                               additional_info={'model': 'v3', 'confidence': probability})
        if not saved:
            # save_alert_log swallows its own errors and leaves the session in a failed state
            print(f"[Camera {camera_id}] V3 alert row was not saved")
            _safe_rollback()
    except Exception:
        print(f"[Camera {camera_id}] V3 alert row failed:\n{traceback.format_exc()}")
        _safe_rollback()

    try:
        notify_fall_alert(camera_id, camera_name, room_name, 'fall_red', current_time, img_path,
                          confidence=probability)
    except Exception:
        print(f"[Camera {camera_id}] V3 notification failed:\n{traceback.format_exc()}")

    print(f"[Camera {camera_id}] V3 FALL ALERT: {label}, Confidence: {probability:.2f}, People seen: {seen_count}")


def _process_v3_fall_detection(camera_id, config):
    """V3 fall detection loop: YOLO-pose + temporal CNN, several people tracked independently.

    Alerting is this repo's own (cooldown, alert image, alert row, notify_fall_alert) and is the same idea as
    the v2 loop below; only the decision of WHAT is a fall comes from v3.
    """
    from app import create_app
    app = create_app()
    with app.app_context():
        from app.services.model_manager import model_manager

        try:
            camera = Camera.query.get(camera_id)
            if not camera:
                save_system_log('ERROR', f'Camera {camera_id} not found for V3 fall detection', 'DETECTION')
                return

            print(f"[V3 Pose] Starting fall detection session for camera {camera.name}")
            save_system_log('INFO', f'V3 Fall detection session started for camera {camera.name}', 'DETECTION', camera.user_id)

            fall_detector = model_manager.get_v3_fall_detector()
            if fall_detector is None:
                save_system_log('ERROR', f'V3 Fall detector not available for camera {camera.name}', 'DETECTION', camera.user_id)
                print(f"[V3 Pose] Fall detector not available for camera {camera.name}")
                return

            cap = cv2.VideoCapture(camera.url)
            if not cap.isOpened():
                save_system_log('ERROR', f'Failed to open camera {camera.name} for V3 fall detection', 'DETECTION', camera.user_id)
                return
            # A live source hands back its newest frame instead of a growing backlog of stale ones
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            fps = cap.get(cv2.CAP_PROP_FPS)
            is_video_file = not camera.url.startswith(('rtsp:', 'rtmp:', 'http:'))
            # The detector instance is shared by every camera in this process: the runner resets its crop state
            runner = V3FallRunner(fall_detector, fps, is_video_file)

            frame_count = 0
            last_log_time = 0
            log_interval = config.get("LOGGING_INTERVAL", 60)  # Default 60 seconds

            while camera.is_active:
                ok, frame, _ = runner.read(cap)
                if not ok:
                    if is_video_file:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Loop video
                        # The window and the tracks must not span the jump back to frame zero
                        runner.reset()
                        continue
                    else:
                        break

                frame_count += 1
                if frame_count % 30 == 0:
                    print(f"[Camera {camera_id}] V3 Fall Detection - Processing frame {frame_count}")

                results, top = runner.step(frame)
                any_detected = any(r[1] for r in results)
                # Credit the alert to a person the detector actually flagged (see alert_result)
                _, _, probability, label, _ = top

                # Save detection log periodically
                now = time.time()
                if now - last_log_time >= log_interval:
                    detection_result = 'fall_v2' if any_detected else 'no_fall'
                    risk_level = 'red' if any_detected else 'normal'
                    save_detection_log(
                        camera_id=camera.id,
                        detection_result=detection_result,
                        confidence_score=probability,
                        risk_level=risk_level,
                        person_count=runner.state.seen_count
                    )
                    print(f"[Camera {camera_id}] V3 Fall Log: {detection_result}, Confidence: {probability:.2f}")
                    last_log_time = now

                if any_detected:
                    now = time.time()
                    alert_cooldown = getattr(camera, 'alert_cooldown', None) or Config.NOTIFICATION_COOLDOWN
                    last_alert_time = getattr(camera, '_last_fall_v2_alert_time', 0)

                    if now - last_alert_time >= alert_cooldown:
                        # The cooldown is spent when an alert is ATTEMPTED, not when it succeeds: a failure that
                        # persists (disk full, database down) must not be retried at frame rate. The next
                        # attempt is one cooldown later.
                        camera._last_fall_v2_alert_time = now
                        try:
                            _raise_v3_fall_alert(camera, frame, probability, label, runner.state.seen_count)
                        except Exception:
                            # Nothing that goes wrong while alerting may end detection: keep watching.
                            print(f"[Camera {camera_id}] V3 alert block failed, detection continues:\n"
                                  f"{traceback.format_exc()}")
                            _safe_rollback()

                db.session.refresh(camera)
                if not camera.is_active:
                    break

                # Without a frame-rate cap a file would be read as fast as the machine can go
                if is_video_file and not runner.min_period and fps > 0:
                    time.sleep(1.0 / fps)

            cap.release()
            save_system_log('INFO', f'V3 Fall detection session ended for camera {camera.name}', 'DETECTION', camera.user_id)

        except Exception as e:
            save_system_log('ERROR', f'V3 Fall detection error for {camera_id}: {str(e)}', 'DETECTION')
            if 'cap' in locals():
                cap.release()
            raise


@celery.task
def process_v2_fall_detection(camera_id, config):
    """Fall detection for a 'fall_v2' camera. Config.FALL_DETECTOR picks the detector:
    'v3' (default) is the pose-based detector; 'v2' runs the original ONNX path, unchanged."""
    mode = (Config.FALL_DETECTOR or 'v3').strip().lower()
    if mode == 'v2':
        return _process_v2_fall_detection_legacy(camera_id, config)
    if mode != 'v3':
        print(f"[Camera {camera_id}] unknown FALL_DETECTOR={mode!r}, using v3 (valid: v3, v2)")
    return _process_v3_fall_detection(camera_id, config)


def _process_v2_fall_detection_legacy(camera_id, config):
    """Process V2 fall detection for a camera (the original ONNX detector, unchanged; FALL_DETECTOR=v2)"""
    from app import create_app
    app = create_app()
    with app.app_context():
        from app.detection.v2_fall_detection_onnx import (
            V2ONNXFallDetectionState, 
            detect_v2_fall_only_onnx
        )
        from app.services.model_manager import model_manager
        
        try:
            camera = Camera.query.get(camera_id)
            if not camera:
                save_system_log('ERROR', f'Camera {camera_id} not found for V2 fall detection', 'DETECTION')
                return
            
            print(f"[V2 ONNX] Starting fall detection session for camera {camera.name}")
            save_system_log('INFO', f'V2 Fall detection session started for camera {camera.name}', 'DETECTION', camera.user_id)
            
            fall_detector = model_manager.get_v2_fall_detector()
            if fall_detector is None:
                save_system_log('ERROR', f'V2 Fall detector not available for camera {camera.name}', 'DETECTION', camera.user_id)
                print(f"[V2 ONNX] Fall detector not available for camera {camera.name}")
                return
            
            print(f"[V2 ONNX] Using pre-loaded fall detector for camera {camera.name}")
            
            # Initialize detection state
            fall_state = V2ONNXFallDetectionState()
            
            # Initialize camera capture
            cap = cv2.VideoCapture(camera.url)
            if not cap.isOpened():
                save_system_log('ERROR', f'Failed to open camera {camera.name} for V2 fall detection', 'DETECTION', camera.user_id)
                return
            
            # Get video properties
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps == 0:
                fps = 30  # Default FPS
            
            is_video_file = not camera.url.startswith(('rtsp:', 'rtmp:', 'http:'))
            
            frame_count = 0
            last_log_time = 0
            log_interval = config.get("LOGGING_INTERVAL", 60)  # Default 60 seconds
            
            while camera.is_active:
                ret, frame = cap.read()
                if not ret:
                    if is_video_file:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Loop video
                        continue
                    else:
                        break
                
                frame_count += 1
                # Print every 30 frames (about 1 second at 30 fps)
                if frame_count % 30 == 0:
                    print(f"[Camera {camera_id}] V2 Fall Detection - Processing frame {frame_count}")
                
                # Perform V2 ONNX fall detection
                detected, probability, label, processed_frame = detect_v2_fall_only_onnx(
                    frame, fall_state, fall_detector, config, camera
                )
                
                # Save detection log periodically
                now = time.time()
                if now - last_log_time >= log_interval:
                    detection_result = 'fall_v2' if detected else 'no_fall'
                    risk_level = 'red' if detected else 'normal'
                    save_detection_log(
                        camera_id=camera.id,
                        detection_result=detection_result,
                        confidence_score=probability,
                        risk_level=risk_level,
                        person_count=1 if detected else 0
                    )
                    print(f"[Camera {camera_id}] V2 Fall Log: {detection_result}, Confidence: {probability:.2f}")
                    last_log_time = now
                
                if detected:
                    
                    # Send alerts
                    current_time = datetime.now(tz)
                    now = time.time()
                    
                    alert_cooldown = getattr(camera, 'alert_cooldown', None) or Config.NOTIFICATION_COOLDOWN
                    last_alert_time = getattr(camera, '_last_fall_v2_alert_time', 0)
                    
                    if now - last_alert_time >= alert_cooldown:
                        # Save image for alert
                        alert_dir = getattr(Config, 'ALERT_IMAGE_DIR', None) or '/app/tmp'
                        os.makedirs(alert_dir, exist_ok=True)
                        img_path = os.path.join(alert_dir, f"v2_fall_detect_{camera_id}_{int(time.time())}.jpg")
                        cv2.imwrite(img_path, processed_frame)
                        
                        save_alert_log(camera.id, 'fall_red', img_path, additional_info={'model': 'v2', 'confidence': probability})
                        send_telegram_message_async(
                            camera.id, camera.name, camera.room_name, 
                            'fall_red', current_time, img_path
                        )
                        
                        print(f"[Camera {camera_id}] V2 FALL ALERT: {label}, Confidence: {probability:.2f}")
                        camera._last_fall_v2_alert_time = now
                
                db.session.refresh(camera)
                if not camera.is_active:
                    break
                
                if is_video_file and fps > 0:
                    time.sleep(1.0 / fps)
            
            cap.release()
            save_system_log('INFO', f'V2 Fall detection session ended for camera {camera.name}', 'DETECTION', camera.user_id)
            
        except Exception as e:
            save_system_log('ERROR', f'V2 Fall detection error for {camera_id}: {str(e)}', 'DETECTION')
            if 'cap' in locals():
                cap.release()
            raise

@celery.task
def process_v2_alone_detection(camera_id, config):
    """Process V2 alone detection for a camera"""
    from app import create_app
    app = create_app()
    with app.app_context():
        from app.detection.v2_fall_detection_onnx import (
            detect_v2_alone_only_onnx
        )
        from app.services.model_manager import model_manager
        
        try:
            camera = Camera.query.get(camera_id)
            if not camera:
                save_system_log('ERROR', f'Camera {camera_id} not found for V2 alone detection', 'DETECTION')
                return
            
            # Check if alone detection is enabled for this camera
            if not getattr(camera, 'enable_alone_detection', True):
                print(f"[V2 ONNX] Alone detection is disabled for camera {camera.name}")
                save_system_log('INFO', f'V2 Alone detection skipped (disabled) for camera {camera.name}', 'DETECTION', camera.user_id)
                return
            
            print(f"[V2 ONNX] Starting alone detection session for camera {camera.name}")
            save_system_log('INFO', f'V2 Alone detection session started for camera {camera.name}', 'DETECTION', camera.user_id)
            
            person_detector = model_manager.get_v2_person_detector()
            if person_detector is None:
                save_system_log('ERROR', f'V2 Person detector not available for camera {camera.name}', 'DETECTION', camera.user_id)
                print(f"[V2 ONNX] Person detector not available for camera {camera.name}")
                return
            
            print(f"[V2 ONNX] Using pre-loaded person detector for camera {camera.name}")
            
            cap = cv2.VideoCapture(camera.url)
            if not cap.isOpened():
                save_system_log('ERROR', f'Failed to open camera {camera.name} for V2 alone detection', 'DETECTION', camera.user_id)
                return
            
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps == 0:
                fps = 30
            
            is_video_file = not camera.url.startswith(('rtsp:', 'rtmp:', 'http:'))
            
            frame_count = 0
            last_log_time = 0
            log_interval = 300
            
            while camera.is_active:
                ret, frame = cap.read()
                if not ret:
                    if is_video_file:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Loop video
                        continue
                    else:
                        break
                
                frame_count += 1
                # Print every 30 frames (about 1 second at 30 fps)
                if frame_count % 30 == 0:
                    print(f"[Camera {camera_id}] V2 Alone Detection - Processing frame {frame_count}")
                
                # Perform V2 ONNX alone detection
                risk_level, person_count, detection_result, processed_frame = detect_v2_alone_only_onnx(
                    frame, person_detector
                )
                
                # Save detection log periodically
                now = time.time()
                if now - last_log_time >= log_interval:
                    save_detection_log(
                        camera_id=camera.id,
                        detection_result=detection_result,
                        confidence_score=1.0,
                        risk_level=risk_level,
                        person_count=person_count
                    )
                    print(f"[Camera {camera_id}] V2 Alone Log: {detection_result}, Risk: {risk_level}, Count: {person_count}")
                    last_log_time = now
                
                if risk_level == "yellow":  # Alone detected
                    
                    # Send alerts with cooldown
                    current_time = datetime.now(tz)
                    now = time.time()
                    
                    alert_cooldown = getattr(camera, 'alert_cooldown', None) or Config.NOTIFICATION_COOLDOWN
                    last_alert_time = getattr(camera, '_last_alone_v2_alert_time', 0)
                    
                    if now - last_alert_time >= alert_cooldown:
                        save_alert_log(camera.id, 'alone_yellow', image_path=None, additional_info={'model': 'v2', 'person_count': person_count})
                        send_telegram_message_async(
                            camera.id, camera.name, camera.room_name,
                            'alone_yellow', current_time, None
                        )
                        
                        print(f"[Camera {camera_id}] V2 ALONE ALERT: {detection_result}, Count: {person_count}")
                        camera._last_alone_v2_alert_time = now
                
                db.session.refresh(camera)
                if not camera.is_active:
                    break
                
                if is_video_file and fps > 0:
                    time.sleep(1.0 / fps)
            
            cap.release()
            save_system_log('INFO', f'V2 Alone detection session ended for camera {camera.name}', 'DETECTION', camera.user_id)
            
        except Exception as e:
            save_system_log('ERROR', f'V2 Alone detection error for {camera_id}: {str(e)}', 'DETECTION')
            if 'cap' in locals():
                cap.release()
            raise

# Legacy task for backward compatibility - now delegates to specific detection tasks
@celery.task
def process_camera(camera_id, detection_type, config):
    """Legacy task that delegates to specific detection tasks"""
    if detection_type == 'bed_exit':
        return process_bed_exit_detection.delay(camera_id, config)
    elif detection_type == 'fall':
        # Start both fall and alone detection tasks
        fall_task = process_fall_detection.delay(camera_id, config)
        alone_task = process_alone_detection.delay(camera_id, config)
        return {'fall_task': fall_task.id, 'alone_task': alone_task.id}
    elif detection_type == 'fall_v2':
        # Start both V2 fall and alone detection tasks
        fall_v2_task = process_v2_fall_detection.delay(camera_id, config)
        alone_v2_task = process_v2_alone_detection.delay(camera_id, config)
        return {'fall_v2_task': fall_v2_task.id, 'alone_v2_task': alone_v2_task.id}
    else:
        # Default to fall detection only
        return process_fall_detection.delay(camera_id, config) 