import win32api
from dataclasses import dataclass, asdict
from typing import List, Tuple, Dict, Optional

@dataclass
class Monitor:
    index: int
    rect: Tuple[int, int, int, int]  # (left, top, right, bottom)
    center: Tuple[int, int]          # (cx, cy)
    device_name: str
    is_primary: bool

@dataclass
class Boundary:
    monitor_a: int          # Left or Top monitor index
    monitor_b: int          # Right or Bottom monitor index
    axis: str               # "yaw" (horizontal transition) or "pitch" (vertical transition)
    threshold: Optional[float] = None  # To be filled during calibration

def get_all_monitors() -> List[Monitor]:
    """
    Enumerates all display monitors connected to the system.
    Returns them sorted by left coordinate, then top coordinate.
    """
    monitors_raw = win32api.EnumDisplayMonitors()
    monitor_list = []
    
    for i, (hMonitor, hdcMonitor, rect) in enumerate(monitors_raw):
        info = win32api.GetMonitorInfo(hMonitor)
        mon_rect = info.get('Monitor')  # (left, top, right, bottom)
        device_name = info.get('Device', f"MONITOR{i}")
        is_primary = bool(info.get('Flags', 0) & 1)  # MONITORINFOF_PRIMARY is 1
        
        left, top, right, bottom = mon_rect
        cx = left + (right - left) // 2
        cy = top + (bottom - top) // 2
        
        monitor_list.append(Monitor(
            index=i,
            rect=mon_rect,
            center=(cx, cy),
            device_name=device_name,
            is_primary=is_primary
        ))
        
    # Sort monitors: primarily Left-to-Right, secondarily Top-to-Bottom
    # This helps order them predictably.
    monitor_list.sort(key=lambda m: (m.rect[0], m.rect[1]))
    
    # Re-assign indices to reflect the sorted order for easier indexing
    for idx, monitor in enumerate(monitor_list):
        monitor.index = idx
        
    return monitor_list

def build_neighbor_graph(monitors: List[Monitor]) -> List[Boundary]:
    """
    Analyzes monitor geometries to find physical boundaries between adjacent monitors.
    Handles coordinate gaps caused by DPI scaling or configuration offsets, with a robust
    center-offset fallback for 2-monitor systems.
    """
    boundaries = []
    num_monitors = len(monitors)
    if num_monitors < 2:
        return boundaries

    # 1. Attempt relaxed adjacency detection (tolerance of up to 400px gaps and staggered overlap)
    tolerance_gap = 400  
    # Allow some staggering offset (e.g. up to 100px vertical or horizontal overlap offset)
    overlap_tolerance = -150

    for i in range(num_monitors):
        m1 = monitors[i]
        r1 = m1.rect  # (left, top, right, bottom)
        for j in range(i + 1, num_monitors):
            m2 = monitors[j]
            r2 = m2.rect
            
            # A. Check horizontal neighbor layout (m1 is left, m2 is right or vice versa)
            # Distance between their horizontal borders should be within tolerance gap
            is_horiz_adjacent = False
            if r1[2] <= r2[0] + 50: # m1 is left
                is_horiz_adjacent = (r2[0] - r1[2]) <= tolerance_gap
            elif r2[2] <= r1[0] + 50: # m2 is left
                is_horiz_adjacent = (r1[0] - r2[2]) <= tolerance_gap
                
            # Vertical intervals must overlap or be near each other
            y_overlap = min(r1[3], r2[3]) - max(r1[1], r2[1])
            is_y_aligned = y_overlap >= overlap_tolerance
            
            if is_horiz_adjacent and is_y_aligned:
                left_idx, right_idx = (m1.index, m2.index) if m1.center[0] < m2.center[0] else (m2.index, m1.index)
                boundary = Boundary(
                    monitor_a=left_idx,
                    monitor_b=right_idx,
                    axis="yaw"
                )
                if boundary not in boundaries:
                    boundaries.append(boundary)
                    
            # B. Check vertical neighbor layout (m1 is top, m2 is bottom or vice versa)
            is_vert_adjacent = False
            if r1[3] <= r2[1] + 50: # m1 is top
                is_vert_adjacent = (r2[1] - r1[3]) <= tolerance_gap
            elif r2[3] <= r1[1] + 50: # m2 is top
                is_vert_adjacent = (r1[1] - r2[3]) <= tolerance_gap
                
            # Horizontal intervals must overlap or be near each other
            x_overlap = min(r1[2], r2[2]) - max(r1[0], r2[0])
            is_x_aligned = x_overlap >= overlap_tolerance
            
            if is_vert_adjacent and is_x_aligned:
                top_idx, bottom_idx = (m1.index, m2.index) if m1.center[1] < m2.center[1] else (m2.index, m1.index)
                boundary = Boundary(
                    monitor_a=top_idx,
                    monitor_b=bottom_idx,
                    axis="pitch"
                )
                if boundary not in boundaries:
                    boundaries.append(boundary)

    # 2. Fallback for 2-monitor systems: if no boundary was found but exactly 2 monitors exist,
    # they MUST share a boundary. We determine the primary axis of separation from their centers.
    if len(boundaries) == 0 and num_monitors == 2:
        m1, m2 = monitors[0], monitors[1]
        cx1, cy1 = m1.center
        cx2, cy2 = m2.center
        
        dx = abs(cx1 - cx2)
        dy = abs(cy1 - cy2)
        
        print(f"[Monitors] Fallback triggered. dx={dx}, dy={dy}", flush=True)
        
        if dx > dy:
            # Horizontally separated
            left_idx = m1.index if cx1 < cx2 else m2.index
            right_idx = m2.index if cx1 < cx2 else m1.index
            boundaries.append(Boundary(
                monitor_a=left_idx,
                monitor_b=right_idx,
                axis="yaw"
            ))
        else:
            # Vertically separated
            top_idx = m1.index if cy1 < cy2 else m2.index
            bottom_idx = m2.index if cy1 < cy2 else m1.index
            boundaries.append(Boundary(
                monitor_a=top_idx,
                monitor_b=bottom_idx,
                axis="pitch"
            ))

    return boundaries

