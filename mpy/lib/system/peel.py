# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# peel.py - Manages the peel motor when triggered

import time
import micropython

class PeelMotor:
    # States
    STATE_STOPPED, STATE_FORWARD, STATE_REVERSE = 0, 1, 2

    def __init__(self, drives, default_speed=75, default_time_ms=1000, dmesg=None, debug_enabled=False):
        self.drives = drives
        self.default_speed, self.default_time_ms = abs(default_speed), default_time_ms
        self.dmesg, self.debug_enabled = dmesg, debug_enabled
        self._current_state = self.STATE_STOPPED
        self._target_run_time_ms = self._run_start_time_ms = self._current_actual_speed = 0
        self._log("PeelMotor initialized.")

    def _log(self, message):
        if self.debug_enabled:
            if self.dmesg and hasattr(self.dmesg, 'log'):
                self.dmesg.log(f"PEEL_MOTOR: {message}")
            else:
                print(f"PEEL_MOTOR: {message}")

    def run(self, direction_int, time_ms=None, speed=None):
        """Commands the peel motor. direction_int: -1=REVERSE, 0=STOP, 1=FORWARD"""
        # Map direction to state
        state_map = {0: self.STATE_STOPPED, 1: self.STATE_FORWARD, -1: self.STATE_REVERSE}
        if direction_int not in state_map:
            self._log(f"Error: Invalid direction {direction_int}. Use -1, 0, or 1.")
            return
        
        direction_state = state_map[direction_int]
        run_time_ms = self.default_time_ms if time_ms is None else time_ms
        
        if run_time_ms < 0:
            self._log(f"Error: Invalid time_ms {run_time_ms}. Must be >= 0.")
            return
        
        actual_speed = min(abs(speed), 100) if speed is not None else self.default_speed
        
        self._log(f"Run: Dir={direction_int} ({self.get_state_name(direction_state)}), Time={run_time_ms}ms, Speed={actual_speed}")

        # Handle immediate stop
        if direction_state == self.STATE_STOPPED or (run_time_ms == 0 and direction_state != self.STATE_STOPPED):
            if self._current_state != self.STATE_STOPPED:
                self._log(f"Immediate stop from {self.get_state_name(self._current_state)}")
            self._set_state(self.STATE_STOPPED, 0)
            return

        # Check if state/speed change needed
        state_changed = (self._current_state != direction_state or 
                        self._current_state == self.STATE_STOPPED or
                        self._current_actual_speed != actual_speed)

        if state_changed:
            if self._current_state == direction_state and self._current_actual_speed != actual_speed:
                self._log(f"Speed change to {actual_speed} in {self.get_state_name(direction_state)}")
            else:
                self._log(f"Starting {self.get_state_name(direction_state)} for {run_time_ms}ms at {actual_speed}")
            
            self._set_state(direction_state, actual_speed)
        
        # Reset timer
        self._run_start_time_ms = time.ticks_ms()
        self._target_run_time_ms = run_time_ms
        
        if not state_changed:
            self._log(f"Timer reset for {run_time_ms}ms in {self.get_state_name(direction_state)}")

    def _set_state(self, new_state, speed_to_use=None):
        """Set motor state and speed."""
        if new_state != self.STATE_STOPPED and speed_to_use is None:
            speed_to_use = self.default_speed
        elif new_state == self.STATE_STOPPED:
            speed_to_use = 0

        # Skip if no change needed (except for stop which always executes)
        if (self._current_state == new_state and new_state != self.STATE_STOPPED and 
            self._current_actual_speed == speed_to_use):
            return

        self._current_state = new_state
        self._current_actual_speed = speed_to_use if new_state != self.STATE_STOPPED else 0

        if new_state == self.STATE_FORWARD:
            self.drives.peel_set(self._current_actual_speed)
            self._log(f"Motor FORWARD (Speed: {self._current_actual_speed})")
        elif new_state == self.STATE_REVERSE:
            self.drives.peel_set(-self._current_actual_speed)
            self._log(f"Motor REVERSE (Speed: {-self._current_actual_speed})")
        elif new_state == self.STATE_STOPPED:
            self.drives.peel_set(0)
            self._run_start_time_ms = self._target_run_time_ms = self._current_actual_speed = 0
            self._log("Motor STOPPED")
        else:
            self._log(f"Error: Invalid state {new_state}")

    def update(self):
        """Update motor state based on timer."""
        if self._current_state == self.STATE_STOPPED or self._target_run_time_ms <= 0:
            return

        elapsed = time.ticks_diff(time.ticks_ms(), self._run_start_time_ms)
        if elapsed >= self._target_run_time_ms:
            self._log(f"Timer complete ({self._target_run_time_ms}ms) - stopping")
            self._set_state(self.STATE_STOPPED, 0)

    def get_state(self):
        """Return current state as integer (-1, 0, 1)."""
        return {self.STATE_FORWARD: 1, self.STATE_REVERSE: -1, self.STATE_STOPPED: 0}[self._current_state]

    def get_state_name(self, state_value=None):
        """Return state name string."""
        state = self._current_state if state_value is None else state_value
        names = {self.STATE_STOPPED: "STOPPED", self.STATE_FORWARD: "FORWARD", self.STATE_REVERSE: "REVERSE"}
        return names.get(state, "UNKNOWN")

    def is_idle(self):
        """Return True if motor is stopped."""
        return self._current_state == self.STATE_STOPPED



