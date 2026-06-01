import keyboard
import threading
from typing import List

class HotkeyManager:
    def __init__(self, camera_worker, initial_hotkey: str = "caps lock+shift"):
        self.camera_worker = camera_worker
        self.keys: List[str] = []
        self.hotkey_str = ""
        self.set_hotkey(initial_hotkey)

    def set_hotkey(self, hotkey_str: str) -> None:
        """Parses and sets a new hotkey combination (e.g. 'caps lock+shift')."""
        self.hotkey_str = hotkey_str.strip().lower()
        # Split combination on '+' and filter empty strings
        self.keys = [k.strip() for k in self.hotkey_str.split('+') if k.strip()]
        print(f"[HotkeyManager] Updated hotkey to: {self.keys}", flush=True)

    def start(self) -> None:
        """Hooks the keyboard events."""
        keyboard.hook(self._callback)

    def stop(self) -> None:
        """Unhooks all keyboard events."""
        try:
            keyboard.unhook(self._callback)
        except Exception:
            pass

    def _callback(self, event) -> None:
        """Callback executed on every key event."""
        # If application is paused or exit requested, turn off camera active state
        if self.camera_worker.app_paused or self.camera_worker.exit_requested.is_set():
            if self.camera_worker.hotkey_active.is_set():
                self.camera_worker.hotkey_active.clear()
            return

        try:
            # Check if all keys in the combination are currently pressed
            if self.keys and all(keyboard.is_pressed(k) for k in self.keys):
                if not self.camera_worker.hotkey_active.is_set():
                    self.camera_worker.hotkey_active.set()
            else:
                if self.camera_worker.hotkey_active.is_set():
                    self.camera_worker.hotkey_active.clear()
        except Exception:
            pass
