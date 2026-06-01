import os
import sys
import queue
import time
import cv2
import keyboard
import argparse

from core.camera import CameraWorker
from core.hotkey import HotkeyManager
from core.config import load_config, config_exists
from ui.server import run_ui
from tray.tray import TrayIconManager

def parse_args():
    parser = argparse.ArgumentParser(description="Glide Head-Tracking Cursor Switcher")
    parser.add_argument(
        "--debug", 
        action="store_true", 
        help="Enable local OpenCV debug camera preview window"
    )
    return parser.parse_args()

def main():
    args = parse_args()
    
    # 1. Load configuration
    config = load_config()
    print("[Glide] Starting application...", flush=True)
    print(f"[Glide] Configured hotkey: {config.hotkey}", flush=True)
    print(f"[Glide] Calibration profile loaded: {'Yes' if config.calibration else 'No'}", flush=True)
    
    # 2. Initialize Camera Worker (pass debug flag)
    camera_worker = CameraWorker(debug=args.debug)
    camera_worker.update_config(config)
    
    # 3. Initialize Hotkey Manager
    hotkey_manager = HotkeyManager(camera_worker, initial_hotkey=config.hotkey)
    
    # 4. Queue for thread-safe main-thread UI window orchestration
    ui_command_queue = queue.Queue()
    
    def on_recalibrate():
        print("[Glide] Queuing Recalibrate UI command...", flush=True)
        ui_command_queue.put("calibrate-view")
        
    def on_settings():
        print("[Glide] Queuing Settings UI command...", flush=True)
        ui_command_queue.put("settings-view")
        
    def on_exit():
        print("[Glide] Shutdown requested...", flush=True)
        camera_worker.exit_requested.set()
        # Push None to wake up the main loop queue
        ui_command_queue.put(None)
        
    # 5. Initialize & Start Tray Icon
    tray_manager = TrayIconManager(
        camera_worker=camera_worker,
        on_recalibrate=on_recalibrate,
        on_settings=on_settings,
        on_exit=on_exit
    )
    tray_manager.start()
    
    # 6. Start Camera Worker Thread
    camera_worker.start()
    
    # 7. Hook Keyboard Listener
    hotkey_manager.start()
    
    # 8. First launch flow: if no calibration exists, display onboarding immediately
    first_launch = not config_exists()
    if first_launch:
        print("[Glide] No calibration found. Triggering first-launch onboarding...", flush=True)
        run_ui(camera_worker, hotkey_manager, start_view="onboarding-view")
        
    print("[Glide] Entering main event loop.", flush=True)
    
    window_open = False
    
    # 9. Main Loop: orchestrates UI openings and OpenCV GUI rendering on the main thread
    while not camera_worker.exit_requested.is_set():
        # A. Check for UI commands
        try:
            # Short timeout to keep loop responsive to exit events
            cmd = ui_command_queue.get(timeout=0.03)
            if cmd is not None:
                print(f"[Glide] Executing UI command: {cmd}", flush=True)
                run_ui(camera_worker, hotkey_manager, start_view=cmd)
                # Re-verify and update configs in case they changed inside the UI
                config = load_config()
                camera_worker.update_config(config)
                hotkey_manager.set_hotkey(config.hotkey)
                tray_manager.update_menu()
        except queue.Empty:
            pass
            
        # B. Handle OpenCV Debug window (only if debug is active)
        if args.debug:
            try:
                frame = camera_worker.frame_queue.get_nowait()
                if frame is None:
                    if window_open:
                        cv2.destroyAllWindows()
                        window_open = False
                else:
                    cv2.imshow("Glide OpenCV Debug Feed", frame)
                    window_open = True
            except queue.Empty:
                pass
                
            # Keep OpenCV window responsive
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                camera_worker.exit_requested.set()
                break
                
        # C. General exit key listener (ESC) via keyboard lib
        if keyboard.is_pressed('esc'):
            print("[Glide] ESC key pressed. Exiting...", flush=True)
            camera_worker.exit_requested.set()
            break
            
    # 10. Cleanup on exit
    print("[Glide] Cleaning up resources...", flush=True)
    hotkey_manager.stop()
    keyboard.unhook_all()
    cv2.destroyAllWindows()
    
    # Graceful stop of tray
    if tray_manager.icon:
        try:
            tray_manager.icon.stop()
        except Exception:
            pass

    # Wait for camera worker thread to finish its cleanup
    if camera_worker.thread.is_alive():
        print("[Glide] Waiting for camera thread to stop...", flush=True)
        camera_worker.thread.join(timeout=3.0)
            
    print("[Glide] Exited cleanly.", flush=True)

if __name__ == "__main__":
    main()
