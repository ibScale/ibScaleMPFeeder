# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# servo.py - Software servo for the tape feeder.
#
# Positioning is closed by WHERE the motor stops, not by a high-rate error loop:
# a feedforward velocity profile (distance -> speed) drives the move, the last
# stretch is held at a slow constant CREEP speed, and the motor brakes the instant
# the encoder crosses the target. Final accuracy therefore depends on a repeatable
# slow stop rather than on tuned PID gains.
#
# The final approach is always FORWARD so gear/sprocket backlash is taken up the
# same way every time. A reverse request first backs off past the target (two-phase),
# then approaches forward. A stall/timeout watchdog turns a jam into a reported fault
# instead of driving indefinitely.

import time
import micropython
from system.peel import PeelMotor
from system.watchdog import feed as wdt_feed

# Motion states
_STATE_IDLE = micropython.const(0)      # at rest, braked; move finished (see result)
_STATE_BACKOFF = micropython.const(1)   # reverse move: running back past the target
_STATE_APPROACH = micropython.const(2)  # running the forward velocity profile
_STATE_SETTLE = micropython.const(3)    # in tolerance, braked, confirming the stop
_STATE_FAULT = micropython.const(4)     # stalled/timed out, braked; result latched

# Move results (map these to protocol responses at the caller)
RESULT_NONE = micropython.const(0)      # in progress / never moved
RESULT_REACHED = micropython.const(1)   # landed within tolerance
RESULT_OVERSHOT = micropython.const(2)  # passed target by >tolerance (grid corrects next move)
RESULT_STALLED = micropython.const(3)   # no encoder progress while driving
RESULT_TIMEOUT = micropython.const(4)   # move exceeded its time budget

_RESULT_NAMES = ('NONE', 'REACHED', 'OVERSHOT', 'STALLED', 'TIMEOUT')


class Servo:
    """Feedforward velocity-profile servo with forward backlash takeup and fault detection."""

    def __init__(self, drives, encoder, dmesg,
                 max_output=80, creep_output=15, min_output=5,
                 tolerance=15, backlash_takeup=200,
                 accel_ticks=200, decel_ticks=250, creep_ticks=150,
                 stable_updates=3, brake=True,
                 stall_ms=300, stall_eps=3, move_timeout_ms=10000,
                 profiles=None, default_profile='normal',
                 peel_enable=False, peel_speed=75, peel_time_ms=1000,
                 debug_enabled=False):

        # Hardware references
        self.drives, self.encoder, self.dmesg = drives, encoder, dmesg
        self.drives.auto_brake = brake

        # Profile parameters (all speeds are drive duty %, all distances are encoder ticks)
        self.max_output = abs(max_output)
        self.creep_output = abs(creep_output)
        self.min_output = abs(min_output)
        self.tolerance = abs(tolerance)
        self.backlash_takeup = abs(backlash_takeup)
        self.accel_ticks = abs(accel_ticks)
        self.decel_ticks = abs(decel_ticks)
        self.creep_ticks = abs(creep_ticks)
        self.stable_updates = stable_updates
        self.debug_enabled = debug_enabled

        # Named speed profiles scale peak speed and accel aggression per move, as
        # (max_scale, accel_scale). The creep tail (CREEP/CREEP_TICKS) is shared, so
        # stop accuracy is constant across profiles - only throughput and part-handling
        # gentleness change. Resolved per move into _active_max / _active_accel.
        self._profiles = dict(profiles) if profiles else {'normal': (1.0, 1.0)}
        if 'normal' not in self._profiles:
            self._profiles['normal'] = (1.0, 1.0)
        self._default_profile = default_profile if default_profile in self._profiles else 'normal'
        self._active_profile = self._default_profile
        self._active_max = self.max_output
        self._active_accel = self.accel_ticks
        self._resolve_profile(self._default_profile)

        # Fault detection
        self.stall_ms = stall_ms
        self.stall_eps = abs(stall_eps)
        self.move_timeout_ms = move_timeout_ms

        # Motion state
        self._state = _STATE_IDLE
        self._result = RESULT_NONE
        self._target = 0
        self._backoff_point = 0
        self._move_start_pos = 0
        self._stable_count = 0

        # Fault tracking
        self._move_start_ms = 0
        self._progress_pos = 0
        self._progress_ms = 0

        # Cumulative commanded grid position (absolute). feed() targets this rather
        # than actual+distance, so each move auto-corrects the previous move's
        # residual instead of accumulating drift over a reel. Seeded to the current
        # encoder position; re-anchor with reseed() on init/fault/manual reposition.
        self._commanded_position = self.encoder.absolute_count

        # PeelMotor integration
        self.peel_motor_enabled_by_servo = peel_enable
        self.default_peel_speed, self.default_peel_run_time_ms = peel_speed, peel_time_ms
        self.peel_motor = PeelMotor(
            drives=self.drives,
            default_speed=self.default_peel_speed,
            default_time_ms=self.default_peel_run_time_ms,
            dmesg=self.dmesg,
            debug_enabled=self.debug_enabled
        )

        self._log(f"Init - Max={self.max_output}, Creep={self.creep_output}, Min={self.min_output}, "
                  f"Tol={self.tolerance}, Backlash={self.backlash_takeup}, "
                  f"Accel/Decel/Creep ticks={self.accel_ticks}/{self.decel_ticks}/{self.creep_ticks}, "
                  f"Stall={self.stall_ms}ms/{self.stall_eps}t, Timeout={self.move_timeout_ms}ms, "
                  f"Profiles={list(self._profiles.keys())} default={self._default_profile}, "
                  f"Peel={'ON' if self.peel_motor_enabled_by_servo else 'OFF'}", force=True)

    def _log(self, msg, force=False):
        if (self.debug_enabled or force) and self.dmesg:
            self.dmesg.log(f"SERVO: {msg}")

    # --- Enable / disable -------------------------------------------------

    def enable(self, state=True):
        if state:
            self.drives.enable(True)
            self._log("Servo enabled.")
        else:
            self.drives.drive_set(0)
            if self.peel_motor_enabled_by_servo:
                self.peel_motor.run(0)
            self._state = _STATE_IDLE
            self.drives.enable(False)
            self._log("Servo disabled.")

    def disable(self):
        self.enable(False)

    @property
    def enabled(self):
        return self.drives.enabled

    # --- Move planning ----------------------------------------------------

    def _resolve_profile(self, name):
        """Set _active_max / _active_accel from a named speed profile for this move."""
        if name is None:
            name = self._default_profile
        scale = self._profiles.get(name)
        if scale is None:
            self._log(f"Unknown profile '{name}', using normal.")
            name = 'normal'
            scale = self._profiles.get('normal', (1.0, 1.0))
        max_scale, accel_scale = scale
        am = self.max_output * max_scale
        am = 100.0 if am > 100.0 else (self.min_output if am < self.min_output else am)
        self._active_max = am
        aa = int(self.accel_ticks * accel_scale)
        self._active_accel = aa if aa >= 1 else 1
        self._active_profile = name

    def set_target(self, target_position, profile=None):
        """Plan and start a move to an absolute encoder position (optional speed profile)."""
        self.enable(True)
        self._resolve_profile(profile)
        self.encoder.update()
        current = self.encoder.absolute_count

        self._target = int(target_position)
        self._result = RESULT_NONE
        self._stable_count = 0
        self._move_start_ms = time.ticks_ms()
        self._reset_progress(current)

        if self._target >= current:
            # Forward move: straight into the approach profile.
            self._begin_approach(current)
        else:
            # Reverse move: back off past the target by enough to give the forward
            # approach a full profile of runway plus the backlash takeup, then come
            # back forward. Final approach is forward in both cases.
            self._backoff_point = self._target - (self.backlash_takeup + self.decel_ticks + self.creep_ticks)
            self._state = _STATE_BACKOFF
            self._move_start_pos = current
            self._log(f"Reverse to {self._target}: backoff to {self._backoff_point}, then approach.")
            if self.peel_motor_enabled_by_servo:
                self.peel_motor.run(-1, self.default_peel_run_time_ms, self.default_peel_speed)

    def _begin_approach(self, current):
        """Enter the forward approach toward self._target from `current`."""
        self._state = _STATE_APPROACH
        self._move_start_pos = current
        self._reset_progress(current)
        remaining = self._target - current
        if remaining <= self.tolerance:
            self._finish(RESULT_REACHED, current)
            return
        self._log(f"Approach to {self._target} (distance {remaining}).")
        if self.peel_motor_enabled_by_servo:
            self.peel_motor.run(1, self.default_peel_run_time_ms, self.default_peel_speed)

    # --- Cumulative grid --------------------------------------------------

    @property
    def commanded_position(self):
        return self._commanded_position

    def reseed(self, position=None):
        """Re-anchor the commanded grid to an absolute position (default: actual encoder).

        Call after INITIALIZE_FEEDER, after a fault, or after any manual repositioning,
        so the next feed() doesn't try to "correct" a discontinuity that isn't real error.
        """
        if position is None:
            self.encoder.update()
            position = self.encoder.absolute_count
        self._commanded_position = int(position)
        self._log(f"Commanded grid reseeded to {self._commanded_position}")
        return self._commanded_position

    def feed(self, distance, profile=None):
        """Advance the commanded grid by `distance` ticks and move to it.

        Targeting the absolute grid (not actual+distance) subtracts the previous move's
        residual automatically, bounding error to a single move. `profile` selects a
        named speed profile for this move. Returns the new target.
        """
        self._commanded_position += int(distance)
        self.set_target(self._commanded_position, profile=profile)
        return self._commanded_position

    # --- Velocity profile -------------------------------------------------

    def _forward_speed(self, remaining, traveled):
        """Forward duty for a given distance remaining and distance already travelled."""
        if remaining <= self.creep_ticks:
            v = self.creep_output
        elif remaining <= self.creep_ticks + self.decel_ticks:
            f = (remaining - self.creep_ticks) / self.decel_ticks  # 1.0 -> 0.0
            v = self.creep_output + (self._active_max - self.creep_output) * f
        else:
            v = self._active_max

        # Accel cap: ramp CREEP -> active MAX over the first accel ticks (soft start).
        if self._active_accel > 0 and traveled < self._active_accel:
            cap = self.creep_output + (self._active_max - self.creep_output) * (traveled / self._active_accel)
            if cap < v:
                v = cap

        return v if v >= self.min_output else self.min_output

    def _reverse_speed(self, remaining):
        """Reverse duty for the backoff phase (no accel cap; precision not required)."""
        if remaining <= self.creep_ticks:
            v = self.creep_output
        elif remaining <= self.creep_ticks + self.decel_ticks:
            f = (remaining - self.creep_ticks) / self.decel_ticks
            v = self.creep_output + (self._active_max - self.creep_output) * f
        else:
            v = self._active_max
        return v if v >= self.min_output else self.min_output

    # --- Fault detection --------------------------------------------------

    def _reset_progress(self, pos):
        now = time.ticks_ms()
        self._progress_pos = pos
        self._progress_ms = now

    def _check_faults(self, pos, check_stall):
        """Return True (and latch a fault) if the move timed out or stalled."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self._move_start_ms) > self.move_timeout_ms:
            self._fault(RESULT_TIMEOUT, pos)
            return True
        if check_stall:
            if abs(pos - self._progress_pos) >= self.stall_eps:
                self._progress_pos = pos
                self._progress_ms = now
            elif time.ticks_diff(now, self._progress_ms) > self.stall_ms:
                self._fault(RESULT_STALLED, pos)
                return True
        return False

    # --- Terminal transitions ---------------------------------------------

    def _finish(self, result, pos):
        self.drives.drive_set(0)  # brake (auto_brake)
        self._state = _STATE_IDLE
        self._result = result
        self._log(f"Done: {_RESULT_NAMES[result]} at {pos} (target {self._target}, err {pos - self._target}).")

    def _fault(self, result, pos):
        self.drives.drive_set(0)
        if self.peel_motor_enabled_by_servo:
            self.peel_motor.run(0)
        self._state = _STATE_FAULT
        self._result = result
        self._log(f"FAULT: {_RESULT_NAMES[result]} at {pos} (target {self._target}).", force=True)

    # --- Control loop -----------------------------------------------------

    @micropython.native
    def update(self):
        if self.peel_motor_enabled_by_servo:
            self.peel_motor.update()

        if not self.enabled:
            if self.peel_motor_enabled_by_servo and not self.peel_motor.is_idle():
                self.peel_motor.run(0)
            return False

        state = self._state
        if state == _STATE_IDLE or state == _STATE_FAULT:
            return False

        self.encoder.update()
        pos = self.encoder.absolute_count

        if state == _STATE_BACKOFF:
            if self._check_faults(pos, True):
                return False
            remaining_back = pos - self._backoff_point
            if remaining_back <= 0:
                self.drives.drive_set(0)
                self._log(f"Backoff complete at {pos}; approaching {self._target}.")
                self._begin_approach(pos)
                return self._state != _STATE_IDLE
            self.drives.drive_set(-self._reverse_speed(remaining_back))
            return True

        if state == _STATE_APPROACH:
            if self._check_faults(pos, True):
                return False
            # Momentum guard: passed the target by more than tolerance.
            if pos > self._target + self.tolerance:
                self._log(f"OVERSHOOT at {pos} (target {self._target}).")
                self._finish(RESULT_OVERSHOT, pos)
                return False
            remaining = self._target - pos
            if remaining <= self.tolerance:
                self.drives.drive_set(0)
                self._state = _STATE_SETTLE
                self._stable_count = 0
                return True
            traveled = abs(pos - self._move_start_pos)
            self.drives.drive_set(self._forward_speed(remaining, traveled))
            return True

        if state == _STATE_SETTLE:
            # Braked; only the overall timeout applies (no stall check while stopped).
            if self._check_faults(pos, False):
                return False
            self.drives.drive_set(0)
            err = pos - self._target
            if abs(err) <= self.tolerance:
                self._stable_count += 1
                if self._stable_count >= self.stable_updates:
                    self._finish(RESULT_REACHED, pos)
                    return False
            elif err < 0:
                # Drifted back below the band: nudge forward again (forward-only).
                self._state = _STATE_APPROACH
                self._move_start_pos = pos
                self._stable_count = 0
                self._reset_progress(pos)
            else:
                # Drifted past the band; can't reverse without reintroducing backlash.
                self._finish(RESULT_OVERSHOT, pos)
                return False
            return True

        return False

    def run_move(self, max_ms=None):
        """Run the active move to completion in a tight real-time loop; return the result.

        Spins update() (which also services the peel motor) as fast as the interpreter
        allows, so the control rate is far above what the jittery async loop would give -
        sub-millisecond per update means ticks-of-travel per cycle stay well under the
        tolerance band. Blocks for the move duration; the stall/timeout watchdog inside
        update() guarantees termination, and max_ms is a belt-and-suspenders backstop.

        RS485 RX (IRQ + micropython.schedule) and the USB FIFO keep buffering during the
        burst, so no incoming packets are lost - they're just processed after the move.
        """
        if max_ms is None:
            max_ms = self.move_timeout_ms + 1000
        start = time.ticks_ms()
        while self.is_busy:
            self.update()
            wdt_feed()  # this loop blocks the main loop, so feed the watchdog here
            if time.ticks_diff(time.ticks_ms(), start) > max_ms:
                self._log("run_move backstop hit; stopping.", force=True)
                self.stop()
                break
        return self._result

    def stop(self):
        self._log("Stop called.")
        self.drives.drive_set(0)
        if self.peel_motor_enabled_by_servo:
            self.peel_motor.run(0)
        self._state = _STATE_IDLE
        self._result = RESULT_NONE

    # --- Status -----------------------------------------------------------

    @property
    def is_busy(self):
        return self._state == _STATE_BACKOFF or self._state == _STATE_APPROACH or self._state == _STATE_SETTLE

    @property
    def result(self):
        return self._result

    @property
    def result_name(self):
        return _RESULT_NAMES[self._result]

    @property
    def active_profile(self):
        return self._active_profile

    @property
    def profiles(self):
        return tuple(self._profiles.keys())

    def get_current_position(self):
        self.encoder.update()
        return self.encoder.absolute_count

    # --- PeelMotor passthrough --------------------------------------------

    def peel_enable(self, enabled: bool):
        self._log(f"Peel motor usage: {enabled}")
        self.peel_motor_enabled_by_servo = enabled
        if not enabled and self.peel_motor:
            self.peel_motor.run(0)
