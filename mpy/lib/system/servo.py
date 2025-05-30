# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# servo.py - Software servo using encoder and drive hardware

# Dear PID gods, get wrekt, unless you wanna reimplement this on your own.
# If I never have to write another PID controller again it will be too soon :)


import time
import micropython
from system.peel import PeelMotor

class Servo:
    """Software Servo with Trajectory Ramp, PID control, and backlash compensation."""

    def __init__(self, drives, encoder, dmesg,
                Kp=0.05, Ki=0.001, Kd=0.005, pid_taper=30,
                max_output=80, min_output=5, backlash_takeup=200,
                tolerance=10, ramp_ticks=200, stable_updates=3,
                ramp_taper_percent=30, brake=True,
                peel_enable=False, peel_speed=75, peel_time_ms=1000,
                debug_enabled=False, derivative_alpha=0.1, dynamic_scale_threshold=100):
        
        # PID Parameters
        self.Kp, self.Ki, self.Kd, self.pid_taper = Kp, Ki, Kd, pid_taper
        self.max_output, self.min_output = abs(max_output), abs(min_output)
        self.backlash_takeup, self.tolerance = abs(backlash_takeup), abs(tolerance)
        self.ramp_ticks, self.stable_updates = abs(ramp_ticks), stable_updates
        self.ramp_taper_percent = max(0, min(100, ramp_taper_percent))
        self.debug_enabled = debug_enabled
        
        # Hardware references
        self.drives, self.encoder, self.dmesg = drives, encoder, dmesg
        self.drives.auto_brake = brake

        # PID state
        self._integral = self._previous_error = 0.0
        self._last_time_us = 0

        # Movement state
        self._setpoint = self._original_setpoint = 0
        self._target_reached = True
        self._stable_count = 0
        self._initial_encoder_pos_at_move_start = self._initial_error_at_move_start = 0

        # Backlash compensation state
        self._backlash_active = self._waiting_for_peel_idle_phase1 = False
        self._current_movement_is_forward = True

        # Derivative filtering
        self._derivative = 0.0
        self._derivative_alpha = derivative_alpha
        self._dynamic_scale_threshold = dynamic_scale_threshold

        # PeelMotor Integration
        self.peel_motor_enabled_by_servo = peel_enable
        self.default_peel_speed, self.default_peel_run_time_ms = peel_speed, peel_time_ms
        
        self.peel_motor = PeelMotor(
            drives=self.drives,
            default_speed=self.default_peel_speed,
            default_time_ms=self.default_peel_run_time_ms,
            dmesg=self.dmesg,
            debug_enabled=self.debug_enabled
        )

        # Always log basic initialization like other hardware components
        self._log(f"Init - PID(Kp={self.Kp}, Ki={self.Ki}, Kd={self.Kd}), MaxOut={self.max_output}, MinOut={self.min_output}, Tol={self.tolerance}, Ramp={self.ramp_ticks}, Backlash={self.backlash_takeup}, Peel={'ON' if self.peel_motor_enabled_by_servo else 'OFF'}", force=True)

    def _log(self, msg, force=False):
        if (self.debug_enabled or force) and self.dmesg:
            self.dmesg.log(f"SERVO: {msg}")

    def enable(self, state=True):
        if state:
            self.drives.enable(True)
            self._log("Servo enabled.")
        else:
            self.drives.drive_set(0)
            if self.peel_motor_enabled_by_servo:
                self.peel_motor.run(0)
            self._target_reached = True
            self._backlash_active = self._waiting_for_peel_idle_phase1 = False
            self.drives.enable(False)
            self._log("Servo disabled.")

    def disable(self):
        self.enable(False)

    @property
    def enabled(self):
        return self.drives.enabled

    def set_target(self, target_position):
        self.enable(True)
        self.encoder.update()
        current_pos = self.encoder.absolute_count

        self._original_setpoint = int(target_position)
        self._target_reached = self._backlash_active = self._waiting_for_peel_idle_phase1 = False

        is_moving_backwards = (self._original_setpoint < current_pos)

        if is_moving_backwards:
            self._log(f"Reverse move to {self._original_setpoint}: two-phase approach.")
            self._backlash_active = True
            overshoot = self.ramp_ticks + self.backlash_takeup
            self._setpoint = self._original_setpoint - overshoot
            self._current_movement_is_forward = False
            self._log(f"Phase 1: Target {self._setpoint}, moving backwards.")
            
            if self.peel_motor_enabled_by_servo:
                if not self.peel_motor.is_idle():
                    self._log("Waiting for peel motor to stop before Phase 1.")
                    self._waiting_for_peel_idle_phase1 = True
                else:
                    self.peel_motor.run(-1, self.default_peel_run_time_ms, self.default_peel_speed)
        else:
            self._setpoint = self._original_setpoint
            if self._setpoint != current_pos:
                self._current_movement_is_forward = (self._setpoint > current_pos)
                if self.peel_motor_enabled_by_servo:
                    self.peel_motor.run(1, self.default_peel_run_time_ms, self.default_peel_speed)
            else:
                self._current_movement_is_forward = True
                if self.peel_motor_enabled_by_servo:
                    self.peel_motor.run(0)
            
            self._log(f"Forward move to {self._setpoint}" if self._setpoint != current_pos else f"Already at target {self._setpoint}")
        
        # Reset control state
        self._integral = 0.0
        self._previous_error = self._setpoint - current_pos
        self._last_time_us = time.ticks_us()
        self._stable_count = 0
        self._initial_encoder_pos_at_move_start = current_pos
        self._initial_error_at_move_start = abs(self._setpoint - current_pos)

        # Check if already within tolerance
        if self._initial_error_at_move_start <= self.tolerance:
            if self._backlash_active and not self._current_movement_is_forward:
                self._log("Phase 1: Near overshoot target.")
            else:
                phase_info = " (Phase 2)" if self._backlash_active else ""
                self._log(f"Target{phase_info} within tolerance. Marking reached.")
                self._target_reached = True
                self.drives.drive_set(0)
                if self._setpoint == current_pos and self.peel_motor_enabled_by_servo:
                    self.peel_motor.run(0)
                if self._backlash_active:
                    self._backlash_active = False

    @micropython.native
    def update(self):
        # Update PeelMotor
        if self.peel_motor_enabled_by_servo:
            self.peel_motor.update()

        if not self.enabled:
            if self.peel_motor_enabled_by_servo and not self.peel_motor.is_idle():
                self.peel_motor.run(0)
            return False

        if self._target_reached and not self._waiting_for_peel_idle_phase1:
            return False

        self.encoder.update()
        current_position = self.encoder.absolute_count

        # Handle waiting for peel motor before Phase 1
        if self._backlash_active and not self._current_movement_is_forward and self._waiting_for_peel_idle_phase1:
            if self.peel_motor_enabled_by_servo and not self.peel_motor.is_idle():
                return True
            else:
                self._log("Peel motor idle. Starting Phase 1.")
                self._waiting_for_peel_idle_phase1 = False
                if self.peel_motor_enabled_by_servo:
                    self.peel_motor.run(-1, self.default_peel_run_time_ms, self.default_peel_speed)

        # Phase 1 completion check
        if self._backlash_active and not self._current_movement_is_forward:
            if current_position <= self._setpoint:
                if not self._waiting_for_peel_idle_phase1:
                    self._log("Phase 1 complete. Waiting for peel motor.")
                    self.drives.drive_set(0)
                    self._waiting_for_peel_idle_phase1 = True
                
                if self.peel_motor_enabled_by_servo and not self.peel_motor.is_idle():
                    return True
                else:
                    self._log("Transitioning to Phase 2.")
                    self._waiting_for_peel_idle_phase1 = False
                    self._setpoint = self._original_setpoint
                    self._current_movement_is_forward = True
                    
                    # Reset for Phase 2
                    self._target_reached = False
                    self._integral = 0.0
                    self._previous_error = self._setpoint - current_position
                    self._last_time_us = time.ticks_us()
                    self._stable_count = 0
                    self._initial_encoder_pos_at_move_start = current_position
                    self._initial_error_at_move_start = abs(self._setpoint - current_position)

                    self._log(f"Phase 2: Target {self._setpoint}")
                    if self.peel_motor_enabled_by_servo:
                        self.peel_motor.run(1, self.default_peel_run_time_ms, self.default_peel_speed)

                    if self._initial_error_at_move_start <= self.tolerance:
                        self._log("Phase 2: Already at target.")
                        self._target_reached = True
                        self.drives.drive_set(0)
                        self._backlash_active = False
                        return False

        if self._waiting_for_peel_idle_phase1:
            return True

        # Movement control logic
        error = self._setpoint - current_position
        distance_to_setpoint = abs(error)

        # Overshoot detection (forward movements only)
        if (self._current_movement_is_forward and current_position > self._setpoint and 
            distance_to_setpoint > self.tolerance):
            phase_info = " (Phase 2)" if self._backlash_active else ""
            self._log(f"OVERSHOOT{phase_info}: Pos={current_position}, Target={self._setpoint}")
            self.drives.drive_set(0)
            self._target_reached = True
            if self._backlash_active:
                self._backlash_active = False
            return False

        # Target reached check
        if distance_to_setpoint <= self.tolerance:
            if not (self._backlash_active and not self._current_movement_is_forward):
                self._stable_count += 1
                if self._stable_count >= self.stable_updates:
                    phase_info = " Phase 2" if self._backlash_active else ""
                    self._log(f"Target reached{phase_info}. Pos={current_position}")
                    self._target_reached = True
                    self.drives.drive_set(0)
                    if self._backlash_active:
                        self._backlash_active = False
                    return False
                else:
                    self.drives.drive_set(0)
        else:
            self._stable_count = 0

        # Control output calculation
        output = 0.0
        
        # Phase 1 reverse control
        if self._backlash_active and not self._current_movement_is_forward:
            reverse_min_speed = self.max_output * 0.6
            total_distance = self._initial_error_at_move_start
            progress = distance_to_setpoint / total_distance if total_distance > 0 else 0
            progress = max(0.0, min(1.0, progress))
            output = -(self.min_output + (reverse_min_speed - self.min_output) * progress)
            output = max(-self.max_output, min(output, -self.min_output))
            
        # Forward control (ramp or PID)
        elif distance_to_setpoint > self.ramp_ticks:  # Ramp phase
            tapered_speed = (self.ramp_taper_percent / 100.0) * self.max_output
            min_ramp_speed = min(max(tapered_speed, self.min_output), self.max_output)
            
            ramp_span = self._initial_error_at_move_start - self.ramp_ticks
            if ramp_span > 0:
                progress = (distance_to_setpoint - self.ramp_ticks) / ramp_span
                progress = max(0.0, min(1.0, progress))
                speed_range = self.max_output - min_ramp_speed
                output = min_ramp_speed + speed_range * progress
            else:
                output = min_ramp_speed
            
            output = min(output, self.max_output)
            
        else:  # PID phase
            if abs(error) <= self.tolerance:
                self.drives.drive_set(0)
            else:
                P = self.Kp * error
                dt = (time.ticks_us() - self._last_time_us) / 1000000.0 if self._last_time_us > 0 else 0.02
                self._integral += error * dt
                max_integral = self.max_output / self.Ki if self.Ki != 0 else self.max_output
                self._integral = max(min(self._integral, max_integral), -max_integral)
                I = self.Ki * self._integral
                
                D = 0.0
                if self._last_time_us > 0 and dt > 0:
                    raw_derivative = (error - self._previous_error) / dt
                    self._derivative = (self._derivative_alpha * raw_derivative + 
                                     (1 - self._derivative_alpha) * self._derivative)
                    D = self.Kd * self._derivative

                output = P + I + D
                output = min(max(output, self.min_output), self.max_output)

        self._previous_error = error
        self._last_time_us = time.ticks_us()
        
        output = max(min(output, self.max_output), -self.max_output)
        self.drives.drive_set(output)
        return True

    def stop(self):
        self._log("Stop called.")
        self.drives.drive_set(0)
        if self.peel_motor_enabled_by_servo:
            self.peel_motor.run(0)
        self._target_reached = True
        self._backlash_active = self._waiting_for_peel_idle_phase1 = False

    @property
    def is_target_reached(self):
        return self._target_reached and not self._waiting_for_peel_idle_phase1

    def get_current_position(self):
        self.encoder.update()
        return self.encoder.absolute_count

    # PeelMotor control methods
    def peel_enable(self, enabled: bool):
        self._log(f"Peel motor usage: {enabled}")
        self.peel_motor_enabled_by_servo = enabled
        if not enabled and self.peel_motor:
            self.peel_motor.run(0)
    
    def peel_state_name(self):
        return self.peel_motor.get_state_name() if self.peel_motor else "Not Initialized"

    def peel_state(self):
        return self.peel_motor.get_state() if self.peel_motor else 0

    def peel_disable(self):
        self.peel_enable(False)