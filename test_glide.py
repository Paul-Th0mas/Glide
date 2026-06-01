import unittest
import os
import json
import tempfile
from unittest.mock import patch, MagicMock

# Import Glide modules
from core.monitors import Monitor, Boundary, build_neighbor_graph
from core.config import Config, CalibrationData, MonitorCalibration, save_config, load_config
from core.cursor import CursorWarpEngine

class TestGlideMonitors(unittest.TestCase):
    def test_horizontal_adjacency(self):
        # Two horizontal monitors side-by-side
        m1 = Monitor(index=0, rect=(0, 0, 1920, 1080), center=(960, 540), device_name="MON1", is_primary=True)
        m2 = Monitor(index=1, rect=(1920, 0, 3840, 1080), center=(2880, 540), device_name="MON2", is_primary=False)
        
        boundaries = build_neighbor_graph([m1, m2])
        self.assertEqual(len(boundaries), 1)
        self.assertEqual(boundaries[0].monitor_a, 0)
        self.assertEqual(boundaries[0].monitor_b, 1)
        self.assertEqual(boundaries[0].axis, "yaw")

    def test_vertical_adjacency(self):
        # Two vertical monitors stacked
        m1 = Monitor(index=0, rect=(0, 0, 1920, 1080), center=(960, 540), device_name="MON1", is_primary=True)
        m2 = Monitor(index=1, rect=(0, 1080, 1920, 2160), center=(960, 1620), device_name="MON2", is_primary=False)
        
        boundaries = build_neighbor_graph([m1, m2])
        self.assertEqual(len(boundaries), 1)
        self.assertEqual(boundaries[0].monitor_a, 0)
        self.assertEqual(boundaries[0].monitor_b, 1)
        self.assertEqual(boundaries[0].axis, "pitch")

    def test_no_adjacency(self):
        # Three monitors, one far apart
        m1 = Monitor(index=0, rect=(0, 0, 1920, 1080), center=(960, 540), device_name="MON1", is_primary=True)
        m2 = Monitor(index=1, rect=(1920, 0, 3840, 1080), center=(2880, 540), device_name="MON2", is_primary=False)
        m3 = Monitor(index=2, rect=(10000, 10000, 11920, 11080), center=(10960, 10540), device_name="MON3", is_primary=False)
        
        boundaries = build_neighbor_graph([m1, m2, m3])
        # Should only detect the boundary between m1 and m2, not m3
        self.assertEqual(len(boundaries), 1)
        self.assertEqual(boundaries[0].monitor_a, 0)
        self.assertEqual(boundaries[0].monitor_b, 1)
        self.assertEqual(boundaries[0].axis, "yaw")

class TestGlideConfig(unittest.TestCase):
    def setUp(self):
        # Create a temp directory for appdata config mocking
        self.temp_dir = tempfile.TemporaryDirectory()
        self.patch_env = patch.dict(os.environ, {"APPDATA": self.temp_dir.name})
        self.patch_env.start()

    def tearDown(self):
        self.patch_env.stop()
        self.temp_dir.cleanup()

    def test_save_load_roundtrip(self):
        # Create corner mock data
        corners = {
            "top_left": [-15.5, 10.0],
            "top_right": [15.5, 10.0],
            "bottom_left": [-15.5, -10.0],
            "bottom_right": [15.5, -10.0]
        }
        monitor = MonitorCalibration(
            index=0, 
            rect=[0, 0, 1920, 1080], 
            center=[960, 540], 
            corners=corners, 
            center_yaw=0.0, 
            center_pitch=0.0
        )
        calibration = CalibrationData(
            monitors=[monitor],
            created_at="2026-05-30T12:00:00"
        )
        config = Config(calibration=calibration, hotkey="ctrl+alt+z")
        
        # Save
        save_config(config)
        
        # Load and verify
        loaded = load_config()
        self.assertEqual(loaded.hotkey, "ctrl+alt+z")
        self.assertIsNotNone(loaded.calibration)
        self.assertEqual(len(loaded.calibration.monitors), 1)
        self.assertEqual(loaded.calibration.monitors[0].corners["top_left"][0], -15.5)

class TestGlideCursorEngine(unittest.TestCase):
    def test_determine_target_monitor_yaw(self):
        engine = CursorWarpEngine(confirmation_frames=1)
        
        # Define monitors: Monitor 0 is Left (center yaw -20.0), Monitor 1 is Right (center yaw 20.0)
        monitors = [
            MonitorCalibration(
                index=0, rect=[0, 0, 1920, 1080], center=[960, 540], 
                corners={}, center_yaw=-20.0, center_pitch=0.0
            ),
            MonitorCalibration(
                index=1, rect=[1920, 0, 3840, 1080], center=[2880, 540], 
                corners={}, center_yaw=20.0, center_pitch=0.0
            )
        ]
        
        # 1. Looking far left (yaw = -15.0) -> closer to Monitor 0
        target = engine.determine_target_monitor(
            smoothed_yaw=-15.0, smoothed_pitch=0.0, current_idx=0, monitors=monitors
        )
        self.assertEqual(target, 0)
        
        # 2. Looking far right (yaw = 15.0) -> closer to Monitor 1
        target = engine.determine_target_monitor(
            smoothed_yaw=15.0, smoothed_pitch=0.0, current_idx=0, monitors=monitors
        )
        self.assertEqual(target, 1)
        
        # 3. Looking far left again (yaw = -10.0) -> closer to Monitor 0
        target = engine.determine_target_monitor(
            smoothed_yaw=-10.0, smoothed_pitch=0.0, current_idx=1, monitors=monitors
        )
        self.assertEqual(target, 0)

    def test_determine_target_monitor_pitch(self):
        engine = CursorWarpEngine(confirmation_frames=1)
        
        # Define monitors: Monitor 0 is Top (center pitch 15.0), Monitor 1 is Bottom (center pitch -15.0)
        monitors = [
            MonitorCalibration(
                index=0, rect=[0, 0, 1920, 1080], center=[960, 540], 
                corners={}, center_yaw=0.0, center_pitch=15.0
            ),
            MonitorCalibration(
                index=1, rect=[0, 1080, 1920, 2160], center=[960, 1620], 
                corners={}, center_yaw=0.0, center_pitch=-15.0
            )
        ]
        
        # 1. Looking up (pitch = 10.0) -> closer to Monitor 0
        target = engine.determine_target_monitor(
            smoothed_yaw=0.0, smoothed_pitch=10.0, current_idx=0, monitors=monitors
        )
        self.assertEqual(target, 0)
        
        # 2. Looking down (pitch = -12.0) -> closer to Monitor 1
        target = engine.determine_target_monitor(
            smoothed_yaw=0.0, smoothed_pitch=-12.0, current_idx=0, monitors=monitors
        )
        self.assertEqual(target, 1)
        
        # 3. Looking up (pitch = 8.0) -> closer to Monitor 0
        target = engine.determine_target_monitor(
            smoothed_yaw=0.0, smoothed_pitch=8.0, current_idx=1, monitors=monitors
        )
        self.assertEqual(target, 0)

if __name__ == '__main__':
    unittest.main()
