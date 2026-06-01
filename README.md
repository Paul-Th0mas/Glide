# Glide — Head-Tracking Multi-Monitor Cursor Switcher

Glide is a lightweight, eye/head-tracking cursor switcher for multi-monitor setups. Instead of dragging your mouse across large desktop areas or multiple screens, Glide allows you to press a hotkey, look at the target monitor, and have your cursor warp instantly to the center of that monitor.

---

## Features

- **Guided Calibration:** A fast 2-step center-only calibration flow that calculates accurate tracking centers without corner dropouts or atan2 wraparound artifacts.
- **Three-Layer Anti-Flicker Engine:**
  - *Hysteresis Margin (4.0°):* Gaze must cross the center threshold convincingly before a monitor switch is registered.
  - *Consecutive Frame Confirmation (5 frames):* Eliminates instant switches caused by temporary tracking noise.
  - *Warp Cooldown (0.4s):* Prevents rapid back-and-forth cursor jumping when looking at screen borders.
- **System Tray Integration:** Run Glide silently in the background, toggle tracking, recalibrate, or edit settings at any time.
- **Low CPU Impact:** Utilizes MediaPipe's FaceMesh Landmarker for lightweight, local head-pose estimation.

---

## Quick Start (For Testers / Users)

1. Run the standalone executable: **`Glide.exe`** (located in the `dist/` directory).
2. The application will start and show the onboarding wizard if this is your first run.
3. Follow the guided calibration:
   - Sit in front of your camera.
   - Look directly at the **centre** of Monitor 1, then Monitor 2, during the 3-second countdowns.
4. **Warping your cursor:**
   - Press and hold **`Caps Lock + Shift`** (the default hotkey).
   - Look at the monitor you want to switch to.
   - Release the hotkey. The cursor warps instantly.
5. **Managing settings:**
   - Right-click the **Glide crosshair icon** in the Windows System Tray to change hotkeys, pause tracking, or recalibrate.

---

## Configuration File

The application stores settings and calibration thresholds under your Windows AppData directory:
```
%APPDATA%\Glide\config.json
```
If you experience any issues, you can delete this file to trigger a fresh onboarding and calibration sequence.

---

## Running & Building from Source

### Prerequisites
- Python 3.10+ on Windows.
- A functional webcam.

### Installation
1. Clone the repository and navigate to the project directory.
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

### Execution
Run the main script:
```bash
python main.py
```
To run with a local camera preview debug window, pass the `--debug` flag:
```bash
python main.py --debug
```

### Packaging a Standalone Executable
To package the app into a single, console-less `.exe` for distribution:
1. Ensure PyInstaller is installed:
   ```bash
   pip install pyinstaller
   ```
2. Compile using the configuration specifications:
   ```bash
   pyinstaller --onefile --noconsole --add-data "assets;assets" --add-data "ui/web;ui/web" --name Glide main.py
   ```
3. Find your built executable at `dist/Glide.exe`.
