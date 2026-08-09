# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# peel.py - Manages the peel motor when triggered

class PeelMotor:
    """Simple peel motor controller: forward, reverse, or stop - no internal timing.

    The peel motor has no notion of "how long" on its own; the caller (Servo) starts
    it when a drive move begins and stops it when the drive move actually ends
    (reached/overshot/faulted/stopped), so peel runtime always tracks the real drive
    runtime instead of guessing a fixed duration up front.

    State tracks commands, not hardware: if the H-bridge is disabled, peel_set() is a
    no-op but the state still advances. The servo enables the drives before commanding
    the peel motor, so this stays consistent in normal use. Stopping brakes the motor
    (peel_set(0) brakes per drives.auto_brake, which the servo sets from SERVO.BRAKE)
    to hold cover-tape tension.
    """
    # States
    STATE_STOPPED, STATE_FORWARD, STATE_REVERSE = 0, 1, 2

    def __init__(self, drives, default_speed=75, dmesg=None, debug_enabled=False):
        self.drives = drives
        self.default_speed = abs(default_speed)
        self.dmesg, self.debug_enabled = dmesg, debug_enabled
        self._current_state = self.STATE_STOPPED
        self._log("PeelMotor initialized.", force=True)

    def _log(self, message, force=False):
        if (self.debug_enabled or force) and self.dmesg:
            self.dmesg.log(f"PEEL_MOTOR: {message}")

    def forward(self, speed=None):
        """Run the peel motor forward (same sense as a forward drive move)."""
        actual_speed = self.default_speed if speed is None else min(abs(speed), 100)
        self._current_state = self.STATE_FORWARD
        self.drives.peel_set(actual_speed)
        self._log(f"Motor FORWARD (Speed: {actual_speed})")

    def reverse(self, speed=None):
        """Run the peel motor reverse (same sense as a reverse/backoff drive move)."""
        actual_speed = self.default_speed if speed is None else min(abs(speed), 100)
        self._current_state = self.STATE_REVERSE
        self.drives.peel_set(-actual_speed)
        self._log(f"Motor REVERSE (Speed: {-actual_speed})")

    def stop(self):
        """Stop the peel motor."""
        self._current_state = self.STATE_STOPPED
        self.drives.peel_set(0)
        self._log("Motor STOPPED")

    def is_idle(self):
        """Return True if motor is stopped."""
        return self._current_state == self.STATE_STOPPED
