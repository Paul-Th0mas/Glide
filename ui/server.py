import os
import time
import threading
import webview
import http.server
import socketserver
from typing import List, Dict, Any, Optional

from core.camera import CameraWorker
from core.hotkey import HotkeyManager
from core.config import Config, CalibrationData, MonitorCalibration, save_config, load_config

MJPEG_PORT = 5000
_server_instance: Optional[socketserver.TCPServer] = None
_server_thread: Optional[threading.Thread] = None

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

class MJPEGHandler(http.server.BaseHTTPRequestHandler):
    """Lightweight handler to stream MJPEG camera feed to the WebView2 control."""
    camera_worker: Optional[CameraWorker] = None

    def log_message(self, format, *args):
        # Override to suppress standard HTTP logging in terminal/console
        pass

    def do_GET(self):
        if self.path.startswith('/video_feed'):
            if not self.camera_worker:
                self.send_response(500)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            
            try:
                # Continuously feed the latest JPEG bytes from camera
                while True:
                    frame_bytes = self.camera_worker.latest_jpeg_frame
                    if frame_bytes is not None:
                        self.wfile.write(b'--frame\r\n')
                        self.wfile.write(b'Content-Type: image/jpeg\r\n')
                        self.wfile.write(f'Content-Length: {len(frame_bytes)}\r\n\r\n'.encode())
                        self.wfile.write(frame_bytes)
                        self.wfile.write(b'\r\n')
                    time.sleep(0.033)  # ~30 FPS
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                # Client disconnected, gracefully exit streaming loop
                pass
        else:
            self.send_response(404)
            self.end_headers()

def start_mjpeg_server(camera_worker: CameraWorker):
    """Starts the local MJPEG HTTP streaming server in a daemon thread."""
    global _server_instance, _server_thread
    if _server_instance is not None:
        return  # Already running

    MJPEGHandler.camera_worker = camera_worker
    
    try:
        _server_instance = ThreadingHTTPServer(('127.0.0.1', MJPEG_PORT), MJPEGHandler)
        _server_thread = threading.Thread(target=_server_instance.serve_forever, daemon=True)
        _server_thread.start()
        print(f"[UI Server] Local MJPEG server started on http://127.0.0.1:{MJPEG_PORT}", flush=True)
    except Exception as e:
        print(f"[UI Server Error] Failed to start MJPEG server: {e}", flush=True)

class GlideAPI:
    """JS-to-Python bridge object exposed in pywebview window."""
    def __init__(self, camera_worker: CameraWorker, hotkey_manager: HotkeyManager, window_ref: List[Optional[webview.Window]]):
        self.camera_worker = camera_worker
        self.hotkey_manager = hotkey_manager
        self.window_ref = window_ref

    def get_monitors(self) -> List[Dict[str, Any]]:
        self.camera_worker.refresh_monitors()
        return [
            {
                "index": m.index,
                "rect": m.rect,
                "center": m.center,
                "device_name": m.device_name,
                "is_primary": m.is_primary
            } for m in self.camera_worker.monitors
        ]

    def get_calibration_steps(self) -> List[Dict[str, Any]]:
        self.camera_worker.refresh_monitors()
        steps = []
        for m in self.camera_worker.monitors:
            steps.append({
                "monitor_index": m.index,
                "type": "center"
            })
        return steps

    def start_calibration(self) -> None:
        self.camera_worker.start_calibration()

    def stop_calibration(self) -> None:
        self.camera_worker.stop_calibration()

    def start_sampling(self) -> None:
        self.camera_worker.start_sampling()

    def stop_sampling_corner(self) -> List[float]:
        yaw, pitch = self.camera_worker.stop_sampling_corner()
        return [yaw, pitch]

    def get_config(self) -> Dict[str, Any]:
        config = load_config()
        cal_dict = None
        if config.calibration:
            cal_dict = {
                "monitors": [
                    {
                        "index": m.index,
                        "rect": m.rect,
                        "center": m.center,
                        "corners": m.corners,
                        "center_yaw": m.center_yaw,
                        "center_pitch": m.center_pitch
                    } for m in config.calibration.monitors
                ],
                "created_at": config.calibration.created_at
            }
        return {
            "calibration": cal_dict,
            "hotkey": config.hotkey
        }

    def save_config(self, config_dict: Dict[str, Any]) -> None:
        cal_dict = config_dict.get('calibration')
        calibration = None
        if cal_dict:
            monitors = []
            for m in cal_dict.get('monitors', []):
                corners = m.get('corners', {})
                c_yaw = m.get('center_yaw', 0.0)
                c_pitch = m.get('center_pitch', 0.0)
                
                # Fallback to computing center from corners if corners are present but center is default
                if corners and c_yaw == 0.0 and c_pitch == 0.0:
                    c_yaw = sum(c[0] for c in corners.values()) / len(corners)
                    c_pitch = sum(c[1] for c in corners.values()) / len(corners)
                
                monitors.append(MonitorCalibration(
                    index=m['index'],
                    rect=m['rect'],
                    center=m['center'],
                    corners=corners,
                    center_yaw=c_yaw,
                    center_pitch=c_pitch
                ))
            calibration = CalibrationData(
                monitors=monitors,
                created_at=cal_dict.get('created_at', '')
            )
        config = Config(calibration=calibration, hotkey=config_dict.get('hotkey', 'caps lock+shift'))
        save_config(config)
        self.camera_worker.update_config(config)
        self.hotkey_manager.set_hotkey(config.hotkey)

    def close_ui(self) -> None:
        print("[UI Server] Closing UI requested.", flush=True)
        if self.window_ref and self.window_ref[0]:
            self.window_ref[0].destroy()
            self.window_ref[0] = None

def run_ui(camera_worker: CameraWorker, hotkey_manager: HotkeyManager, start_view: str = "onboarding-view") -> None:
    """Launches the pywebview application window."""
    start_mjpeg_server(camera_worker)
    
    # Path to web content
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
    html_path = os.path.join(web_dir, 'index.html')
    
    # We use a list wrapper for window reference to modify it inside the callback
    window_ref: List[Optional[webview.Window]] = [None]
    api = GlideAPI(camera_worker, hotkey_manager, window_ref)
    
    window = webview.create_window(
        title="Glide Setup & Settings",
        url=html_path,
        js_api=api,
        width=850,
        height=720,
        resizable=False
    )
    window_ref[0] = window

    def on_loaded():
        # Once the DOM is ready, routes directly to the requested start page
        window.evaluate_js(f"showView('{start_view}')")

    window.events.loaded += on_loaded

    print(f"[UI Server] Opening UI window pointing to {start_view} view...", flush=True)
    webview.start()
    
    # After the window is closed, ensure camera calibration modes are turned off
    camera_worker.stop_calibration()
    print("[UI Server] UI window closed.", flush=True)
