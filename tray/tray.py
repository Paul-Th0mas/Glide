import pystray
import threading
from PIL import Image, ImageDraw
from typing import Callable, Optional

from core.camera import CameraWorker

def create_tray_icon_image() -> Image.Image:
    """Generates a dynamic RGBA image representing the Glide application logo."""
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Draw a cyan crosshair outer ring
    draw.ellipse((8, 8, 56, 56), outline=(0, 229, 255, 255), width=6)
    # Draw a neon green center dot
    draw.ellipse((24, 24, 40, 40), fill=(0, 255, 136, 255))
    return image

class TrayIconManager:
    def __init__(
        self,
        camera_worker: CameraWorker,
        on_recalibrate: Callable[[], None],
        on_settings: Callable[[], None],
        on_exit: Callable[[], None]
    ):
        self.camera_worker = camera_worker
        self.on_recalibrate = on_recalibrate
        self.on_settings = on_settings
        self.on_exit = on_exit
        self.icon: Optional[pystray.Icon] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Launches the system tray loop in a background thread."""
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def update_menu(self) -> None:
        """Forces the tray icon to redraw the menu with updated state labels."""
        if self.icon:
            self.icon.menu = self._build_menu()

    def _build_menu(self) -> pystray.Menu:
        status_text = "Glide: Paused" if self.camera_worker.app_paused else "Glide: Tracking Active"
        pause_action_text = "Resume Tracking" if self.camera_worker.app_paused else "Pause Tracking"
        
        return pystray.Menu(
            pystray.MenuItem(status_text, lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(pause_action_text, self._toggle_pause),
            pystray.MenuItem('Recalibrate...', self._recalibrate),
            pystray.MenuItem('Settings...', self._settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Exit Glide', self._exit)
        )

    def _toggle_pause(self, icon, item) -> None:
        self.camera_worker.app_paused = not self.camera_worker.app_paused
        print(f"[Tray] Toggled pause state. app_paused = {self.camera_worker.app_paused}", flush=True)
        if self.camera_worker.app_paused:
            self.camera_worker.hotkey_active.clear()
        self.update_menu()

    def _recalibrate(self, icon, item) -> None:
        self.on_recalibrate()

    def _settings(self, icon, item) -> None:
        self.on_settings()

    def _exit(self, icon, item) -> None:
        print("[Tray] Shutting down application...", flush=True)
        self.on_exit()
        if self.icon:
            self.icon.stop()

    def _run(self) -> None:
        icon_image = create_tray_icon_image()
        self.icon = pystray.Icon(
            "Glide",
            icon_image,
            "Glide Gaze Monitor Switcher",
            self._build_menu()
        )
        # Blocks inside run()
        self.icon.run()
