import time
import math
import win32api
from typing import List, Tuple, Dict, Any, Optional


class CursorWarpEngine:
    def __init__(
        self,
        cooldown_seconds: float = 0.4,
        hysteresis_margin: float = 4.0,
        confirmation_frames: int = 5,
    ):
        self.cooldown_seconds = cooldown_seconds
        self.last_warp_time = 0.0

        # --- Layer 1: Hysteresis margin ---
        # The new candidate monitor must beat the current one by this many degrees
        # before it is even considered. Absorbs small head wobble at the boundary.
        self.hysteresis_margin = hysteresis_margin

        # --- Layer 2: Consecutive frame confirmation ---
        # Even after the margin is exceeded, the candidate must win on this many
        # *consecutive* frames before the warp fires.  One noisy frame cannot
        # trigger a switch; the head pose must be consistently pointing elsewhere.
        self.confirmation_frames = confirmation_frames

        # Internal state for the confirmation counter
        self._candidate_idx: Optional[int] = None   # monitor we are "voting" towards
        self._candidate_count: int = 0              # consecutive frames voting for it

    # ------------------------------------------------------------------
    def get_current_monitor_index(
        self, cursor_pos: Tuple[int, int], monitors: List[Any]
    ) -> int:
        """Finds which monitor index currently contains the mouse cursor."""
        cx, cy = cursor_pos
        for monitor in monitors:
            if hasattr(monitor, "rect"):
                left, top, right, bottom = monitor.rect
                index = monitor.index
            else:
                left, top, right, bottom = monitor["rect"]
                index = monitor["index"]

            if left <= cx < right and top <= cy < bottom:
                return index
        return 0  # Default to first monitor if not found

    # ------------------------------------------------------------------
    def determine_target_monitor(
        self,
        smoothed_yaw: float,
        smoothed_pitch: float,
        current_idx: int,
        monitors: List[Any],
    ) -> int:
        """
        Returns the monitor index the cursor should be on, using three layers of
        stability to prevent back-and-forth jumping:

        Layer 1 – Hysteresis margin:
            The new candidate must beat the current monitor's distance by at least
            `hysteresis_margin` degrees.  Head wobble near the midpoint will not
            exceed this margin and is therefore ignored.

        Layer 2 – Consecutive frame confirmation:
            Even after the margin is exceeded the candidate must remain the winner
            for `confirmation_frames` consecutive frames (~300 ms at 30 fps).
            A single noisy frame cannot trigger a switch.

        Layer 3 – Warp cooldown (in warp_to_monitor):
            After a warp fires, no further warp can happen for `cooldown_seconds`.
        """
        if not monitors:
            return current_idx

        # --- Compute distance from head pose to every monitor's calibrated centre ---
        distances: Dict[int, float] = {}
        for m in monitors:
            if hasattr(m, "center_yaw"):
                center_yaw = m.center_yaw
                center_pitch = m.center_pitch
                index = m.index
            else:
                center_yaw = m["center_yaw"]
                center_pitch = m["center_pitch"]
                index = m["index"]

            dist = math.sqrt(
                (smoothed_yaw - center_yaw) ** 2
                + (smoothed_pitch - center_pitch) ** 2
            )
            distances[index] = dist

        if not distances:
            return current_idx

        # --- Layer 1: Hysteresis ---
        best_idx = min(distances, key=lambda i: distances[i])

        if best_idx != current_idx:
            current_dist = distances.get(current_idx, float("inf"))
            best_dist = distances[best_idx]
            if (current_dist - best_dist) < self.hysteresis_margin:
                # Candidate is not convincingly closer – reset counter and stay put.
                self._candidate_idx = None
                self._candidate_count = 0
                return current_idx

        # --- Layer 2: Consecutive frame confirmation ---
        if best_idx == current_idx:
            # Gaze is back on the current monitor – reset any pending switch.
            self._candidate_idx = None
            self._candidate_count = 0
            return current_idx

        # A different monitor has cleared the hysteresis margin this frame.
        if self._candidate_idx == best_idx:
            self._candidate_count += 1
        else:
            # New candidate – start a fresh count.
            self._candidate_idx = best_idx
            self._candidate_count = 1

        if self._candidate_count >= self.confirmation_frames:
            # Enough consecutive frames agree – commit to the switch.
            print(
                f"[Warp] Confirmed switch to Monitor {best_idx} "
                f"after {self._candidate_count} frames "
                f"(margin {distances.get(current_idx, 0) - distances[best_idx]:.1f}°)",
                flush=True,
            )
            self._candidate_idx = None
            self._candidate_count = 0
            return best_idx

        # Still building up confirmation frames – stay on current monitor.
        return current_idx

    # ------------------------------------------------------------------
    def reset_candidate(self) -> None:
        """Clears the pending-switch state.  Call when the active monitor changes
        externally (e.g. on hotkey activation) so stale vote counts are discarded."""
        self._candidate_idx = None
        self._candidate_count = 0

    # ------------------------------------------------------------------
    def warp_to_monitor(self, target_idx: int, monitors: List[Any]) -> bool:
        """Warps the mouse cursor to the centre of the target monitor."""
        now = time.time()
        if now - self.last_warp_time < self.cooldown_seconds:
            # Layer 3: cooldown – suppress warping to prevent rapid re-firing
            return False

        for monitor in monitors:
            if hasattr(monitor, "index"):
                index = monitor.index
                center = monitor.center
            else:
                index = monitor["index"]
                center = monitor["center"]

            if index == target_idx:
                try:
                    cx, cy = center
                    win32api.SetCursorPos((cx, cy))
                    self.last_warp_time = now
                    print(
                        f"[Warp] Cursor warped to Monitor {target_idx} center: ({cx}, {cy})",
                        flush=True,
                    )
                    return True
                except Exception as e:
                    print(f"[Warp Error] Failed to set cursor position: {e}", flush=True)
                    return False
        return False
