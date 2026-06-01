import os
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

@dataclass
class MonitorCalibration:
    index: int
    rect: List[int]                    # [left, top, right, bottom]
    center: List[int]                  # [cx, cy]
    corners: Dict[str, List[float]]    # {"top_left": [yaw, pitch], ...}
    center_yaw: float
    center_pitch: float

@dataclass
class CalibrationData:
    monitors: List[MonitorCalibration]
    created_at: str

@dataclass
class Config:
    calibration: Optional[CalibrationData] = None
    hotkey: str = "caps lock+shift"

def get_config_dir() -> str:
    """Returns the path to the application data directory."""
    appdata = os.environ.get('APPDATA')
    if not appdata:
        appdata = os.path.expanduser('~')
    config_dir = os.path.join(appdata, 'Glide')
    os.makedirs(config_dir, exist_ok=True)
    return config_dir

def get_config_path() -> str:
    """Returns the path to the config file."""
    return os.path.join(get_config_dir(), 'config.json')

def save_config(config: Config) -> None:
    """Saves the configuration to the JSON file."""
    path = get_config_path()
    try:
        data = asdict(config)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        print(f"[Config] Configuration saved to {path}", flush=True)
    except Exception as e:
        print(f"[Config Error] Failed to save config: {e}", flush=True)

def load_config() -> Config:
    """Loads configuration from JSON file. Returns a default Config if file does not exist or is invalid."""
    path = get_config_path()
    if not os.path.exists(path):
        print("[Config] No config file found. Using defaults.", flush=True)
        return Config()
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        hotkey = data.get('hotkey', 'caps lock+shift')
        cal_data = data.get('calibration')
        
        calibration = None
        if cal_data:
            monitors = []
            for m in cal_data.get('monitors', []):
                # Ensure compatibility by checking keys
                if 'corners' in m:
                    monitors.append(MonitorCalibration(
                        index=m['index'],
                        rect=m['rect'],
                        center=m['center'],
                        corners=m['corners'],
                        center_yaw=m['center_yaw'],
                        center_pitch=m['center_pitch']
                    ))
            if monitors:
                calibration = CalibrationData(
                    monitors=monitors,
                    created_at=cal_data.get('created_at', '')
                )
            
        return Config(calibration=calibration, hotkey=hotkey)
    except Exception as e:
        print(f"[Config Error] Failed to load config, returning default: {e}", flush=True)
        return Config()

def config_exists() -> bool:
    """Checks if a valid calibration configuration exists."""
    config = load_config()
    return config.calibration is not None and len(config.calibration.monitors) > 0

