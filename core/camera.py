import os
import cv2
import time
import math
import queue
import threading
import numpy as np
import mediapipe as mp
import win32api
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from typing import List, Tuple, Dict, Any, Optional

from core.monitors import get_all_monitors
from core.cursor import CursorWarpEngine
from core.config import Config, load_config

# 3D model points of a generic human face (origin = nose tip)
MODEL_POINTS = np.array([
    (0.0, 0.0, 0.0),             # Nose tip      (index 1)
    (0.0, 330.0, -65.0),         # Chin          (index 152)
    (-225.0, -170.0, -135.0),    # Left eye outer (index 263)
    (-70.0, -170.0, -125.0),     # Left eye inner (index 362)
    (70.0, -170.0, -125.0),      # Right eye inner(index 133)
    (225.0, -170.0, -135.0),     # Right eye outer(index 33)
    (-150.0, 150.0, -125.0),     # Left mouth corner (index 291)
    (150.0, 150.0, -125.0),      # Right mouth corner(index 61)
], dtype="double")

# 3D axis lines for drawing head orientation (length = 150)
AXIS_3D = np.array([
    (150.0, 0.0, 0.0),   # X axis -> Red
    (0.0, 150.0, 0.0),   # Y axis -> Green
    (0.0, 0.0, 150.0),   # Z axis -> Blue
], dtype="double")

def get_model_path() -> str:
    """Finds the MediaPipe model path in the project workspace."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    possible_paths = [
        os.path.join(base_dir, "face_landmarker.task"),
        os.path.join(base_dir, "assets", "face_landmarker.task"),
        os.path.join(os.getcwd(), "face_landmarker.task"),
        os.path.join(os.getcwd(), "assets", "face_landmarker.task")
    ]
    for path in possible_paths:
        if os.path.exists(path):
            print(f"[Camera] Found model at: {path}", flush=True)
            return path
    raise FileNotFoundError("Could not locate face_landmarker.task in Glide workspace.")

class CameraWorker:
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.hotkey_active = threading.Event()
        self.exit_requested = threading.Event()
        self.app_paused = False
        
        # Calibration state
        self.calibration_active = False
        self.capture_samples = False
        self.collected_samples: List[Tuple[float, float]] = []  # List of (yaw, pitch)
        
        # Threading communication
        self.latest_jpeg_frame: Optional[bytes] = None
        self.frame_queue = queue.Queue(maxsize=1)  # For OpenCV debug window in main thread
        
        # State tracking
        self.config: Config = load_config()
        self.warp_engine = CursorWarpEngine()
        self.yaw_history: List[float] = []
        self.pitch_history: List[float] = []
        self.current_monitor_idx = 0
        self.monitors = get_all_monitors()
        
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        """Starts the camera worker background thread."""
        self.thread.start()

    def update_config(self, new_config: Config):
        """Updates the configuration in memory."""
        self.config = new_config

    def refresh_monitors(self):
        """Re-detects connected monitors."""
        self.monitors = get_all_monitors()

    def start_calibration(self):
        """Turns on camera calibration mode (keeps camera feed active)."""
        self.calibration_active = True
        self.collected_samples.clear()

    def stop_calibration(self):
        """Turns off camera calibration mode."""
        self.calibration_active = False
        self.capture_samples = False
        self.collected_samples.clear()

    def start_sampling(self):
        """Starts collecting yaw/pitch samples for calibration."""
        self.collected_samples.clear()
        self.capture_samples = True

    def stop_sampling(self, axis: str = "yaw") -> float:
        # Backwards compatibility / stub in case anything calls it
        val, _ = self.stop_sampling_corner()
        return val

    def stop_sampling_corner(self) -> Tuple[float, float]:
        """
        Stops collecting samples for a corner, filters outliers, and returns the average (yaw, pitch).
        """
        self.capture_samples = False
        if not self.collected_samples:
            return 0.0, 0.0
            
        yaws = [s[0] for s in self.collected_samples]
        pitches = [s[1] for s in self.collected_samples]
        self.collected_samples.clear()
        
        # Filter outliers for yaw
        yaws.sort()
        n = len(yaws)
        if n >= 5:
            trim = int(n * 0.15)
            trimmed_yaws = yaws[trim : n - trim]
        else:
            trimmed_yaws = yaws
            
        # Filter outliers for pitch
        pitches.sort()
        n = len(pitches)
        if n >= 5:
            trim = int(n * 0.15)
            trimmed_pitches = pitches[trim : n - trim]
        else:
            trimmed_pitches = pitches
            
        avg_yaw = sum(trimmed_yaws) / len(trimmed_yaws)
        avg_pitch = sum(trimmed_pitches) / len(trimmed_pitches)
        
        print(f"[Calibration] Finished corner sampling. Total samples: {n}, Average Yaw: {avg_yaw:.2f}°, Average Pitch: {avg_pitch:.2f}°", flush=True)
        return avg_yaw, avg_pitch

    def _run(self):
        model_path = get_model_path()
        base_options = mp_python.BaseOptions(model_asset_path=model_path)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
        )
        landmarker = vision.FaceLandmarker.create_from_options(options)

        cap = None
        frame_timestamp_ms = 0
        camera_matrix = None
        dist_coeffs = None
        width = height = 0
        last_hotkey_state = False

        while not self.exit_requested.is_set():
            # Check if camera should be running
            camera_should_run = (self.hotkey_active.is_set() and not self.app_paused) or self.calibration_active

            if camera_should_run:
                # Initialize Video Capture
                if cap is None:
                    print("[Camera] Turning camera ON...", flush=True)
                    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                    if not cap.isOpened():
                        print("[Camera Error] Could not open webcam via CAP_DSHOW.", flush=True)
                        cap = None
                        time.sleep(0.5)
                        continue
                    
                    # Read a throwaway frame
                    cap.read()
                    
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        print("[Camera Error] Failed to read initial frame.", flush=True)
                        cap.release()
                        cap = None
                        time.sleep(0.5)
                        continue
                        
                    height, width, _ = frame.shape
                    focal_length = width
                    center = (width / 2.0, height / 2.0)
                    camera_matrix = np.array([
                        [focal_length, 0, center[0]],
                        [0, focal_length, center[1]],
                        [0, 0, 1],
                    ], dtype="double")
                    dist_coeffs = np.zeros((4, 1))

                # Handle transition into runtime active state
                if self.hotkey_active.is_set() and not last_hotkey_state:
                    self.refresh_monitors()
                    try:
                        cursor_pos = win32api.GetCursorPos()
                        self.current_monitor_idx = self.warp_engine.get_current_monitor_index(cursor_pos, self.monitors)
                        self.warp_engine.reset_candidate()  # discard any stale vote counts
                        print(
                            f"[Warp Engine] Active. Current monitor: {self.current_monitor_idx} | "
                            f"Hysteresis: {self.warp_engine.hysteresis_margin:.1f}° | "
                            f"Confirmation: {self.warp_engine.confirmation_frames} frames | "
                            f"Cooldown: {self.warp_engine.cooldown_seconds:.1f}s",
                            flush=True
                        )
                    except Exception as e:
                        print(f"[Warp Engine Error] {e}", flush=True)
                    self.yaw_history.clear()
                    self.pitch_history.clear()
                    last_hotkey_state = True

                # Read frame
                ret, frame = cap.read()
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue

                # Process landmarks
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                frame_timestamp_ms += 33
                result = landmarker.detect_for_video(mp_image, frame_timestamp_ms)

                face_detected = False
                yaw = pitch = 0.0
                smoothed_yaw = smoothed_pitch = 0.0

                if result.face_landmarks:
                    face_landmarks = result.face_landmarks[0]
                    indices = [1, 152, 263, 362, 133, 33, 291, 61]
                    image_points = []

                    for idx in indices:
                        lm = face_landmarks[idx]
                        x = int(lm.x * width)
                        y = int(lm.y * height)
                        image_points.append((x, y))
                        # Draw tracking dots on the camera preview
                        cv2.circle(frame, (x, y), 4, (0, 255, 136), -1)

                    image_points = np.array(image_points, dtype="double")

                    success, rvec, tvec = cv2.solvePnP(
                        MODEL_POINTS, image_points, camera_matrix, dist_coeffs,
                        flags=cv2.SOLVEPNP_ITERATIVE
                    )

                    if success:
                        face_detected = True
                        rmat, _ = cv2.Rodrigues(rvec)
                        
                        # Yaw: negative = looking left, positive = looking right
                        yaw = -math.atan2(rmat[0, 2], rmat[2, 2]) * 180.0 / math.pi
                        # Pitch: negative = looking down, positive = looking up
                        pitch = -math.atan2(rmat[1, 2], math.sqrt(rmat[0, 2]**2 + rmat[2, 2]**2)) * 180.0 / math.pi

                        # Apply moving average filter (5-frame window for stability)
                        self.yaw_history.append(yaw)
                        if len(self.yaw_history) > 5:
                            self.yaw_history.pop(0)
                        smoothed_yaw = sum(self.yaw_history) / len(self.yaw_history)

                        self.pitch_history.append(pitch)
                        if len(self.pitch_history) > 5:
                            self.pitch_history.pop(0)
                        smoothed_pitch = sum(self.pitch_history) / len(self.pitch_history)

                        # Calibration Sampling
                        if self.calibration_active and self.capture_samples:
                            self.collected_samples.append((yaw, pitch))

                        # Runtime Cursor Warping Check
                        if self.hotkey_active.is_set() and not self.app_paused and self.config.calibration:
                            target_monitor = self.warp_engine.determine_target_monitor(
                                smoothed_yaw,
                                smoothed_pitch,
                                self.current_monitor_idx,
                                self.config.calibration.monitors
                            )
                            if target_monitor != self.current_monitor_idx:
                                # Trigger Warp
                                if self.warp_engine.warp_to_monitor(target_monitor, self.config.calibration.monitors):
                                    self.current_monitor_idx = target_monitor

                        # Draw 3D axis lines
                        try:
                            (pts2d, _) = cv2.projectPoints(AXIS_3D, rvec, tvec, camera_matrix, dist_coeffs)
                            p0 = (int(image_points[0][0]), int(image_points[0][1]))
                            cv2.line(frame, p0, (int(pts2d[0][0][0]), int(pts2d[0][0][1])), (0, 0, 255), 2)  # X: Red
                            cv2.line(frame, p0, (int(pts2d[1][0][0]), int(pts2d[1][0][1])), (0, 255, 0), 2)  # Y: Green
                            cv2.line(frame, p0, (int(pts2d[2][0][0]), int(pts2d[2][0][1])), (255, 0, 0), 2)  # Z: Blue
                        except Exception:
                            pass

                # Draw status info overlay on MJPEG frame
                if not face_detected:
                    cv2.putText(frame, "NO FACE DETECTED", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                else:
                    cv2.putText(frame, f"Yaw: {smoothed_yaw:+.1f} (Smooth)", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 136), 2)
                    cv2.putText(frame, f"Pitch: {smoothed_pitch:+.1f} (Smooth)", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 136), 2)
                    
                    if self.calibration_active:
                        status_str = "CALIBRATING..." if self.capture_samples else "STANDBY"
                        cv2.putText(frame, f"Status: {status_str}", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 229, 255), 2)
                    else:
                        cv2.putText(frame, f"Active Monitor: {self.current_monitor_idx}", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 229, 255), 2)

                # Encode frame as JPEG bytes for MJPEG HTTP feed
                try:
                    ret, jpeg = cv2.imencode('.jpg', frame)
                    if ret:
                        self.latest_jpeg_frame = jpeg.tobytes()
                except Exception as e:
                    print(f"[Camera Error] JPEG encoding error: {e}", flush=True)

                # OpenCV local debug window support (only in debug mode)
                if self.debug and self.hotkey_active.is_set():
                    try:
                        self.frame_queue.put_nowait(frame)
                    except queue.Full:
                        try:
                            self.frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                        self.frame_queue.put_nowait(frame)

                time.sleep(0.03)  # ~30 FPS

            else:
                # Release Camera when inactive
                if cap is not None:
                    print("[Camera] Turning camera OFF...", flush=True)
                    cap.release()
                    cap = None
                    self.latest_jpeg_frame = None
                    last_hotkey_state = False
                    # Close OpenCV debug window
                    if self.debug:
                        try:
                            self.frame_queue.put_nowait(None)
                        except queue.Full:
                            pass
                            
                time.sleep(0.05)

        # Cleanup
        if cap is not None:
            cap.release()
        landmarker.close()
        print("[Camera] Worker terminated.", flush=True)
