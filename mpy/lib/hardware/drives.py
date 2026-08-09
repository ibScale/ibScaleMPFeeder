# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# drives.py - Motor controller for DRIVE and PEEL motor

import pyb
import machine
import micropython

class HBridge:
    """Motor controller for DRIVE and PEEL motors using PWM H-bridge."""
    
    def __init__(self, peel1, peel2, drive1, drive2, enable,
                 peelinvert=False, driveinvert=False, enableinvert=False, timer_id=4, pwm_frequency=25000,
                 peel1_ch=1, peel2_ch=2, drive1_ch=3, drive2_ch=4, drive_pwm_min=65, peel_pwm_min=65, autobrake=False, DMESG=None, LOG=False):
        
        self.DMESG, self.LOG = DMESG, LOG
        self.drive_pwm_min, self.peel_pwm_min, self.auto_brake = drive_pwm_min, peel_pwm_min, autobrake
        self._enabled = False
        
        # Validate PWM minimums
        if not (0 <= drive_pwm_min <= 100 and 0 <= peel_pwm_min <= 100):
            raise ValueError("PWM minimums must be 0-100")
        
        # Setup pin assignments with inversion
        self.peel1_pin = peel2 if peelinvert else peel1
        self.peel2_pin = peel1 if peelinvert else peel2
        self.drive1_pin = drive2 if driveinvert else drive1
        self.drive2_pin = drive1 if driveinvert else drive2
        self.peel1_ch = peel2_ch if peelinvert else peel1_ch
        self.peel2_ch = peel1_ch if peelinvert else peel2_ch
        self.drive1_ch = drive2_ch if driveinvert else drive1_ch
        self.drive2_ch = drive1_ch if driveinvert else drive2_ch
        self.enable_pin_name, self.enable_invert = enable, enableinvert
        
        self._log(f"Init - Timer: {timer_id}@{pwm_frequency}Hz, PWMMin Drive/Peel:{drive_pwm_min}/{peel_pwm_min}, Inv Drive/Peel/Enable:{peelinvert}/{driveinvert}/{enableinvert}", force=True)
        
        try:
            # Setup PWM timer and channels
            self.timer = pyb.Timer(timer_id, freq=pwm_frequency)
            
            # Initialize pins and PWM channels
            self.peel1_pwm = self.timer.channel(self.peel1_ch, pyb.Timer.PWM, pin=pyb.Pin(self.peel1_pin))
            self.peel2_pwm = self.timer.channel(self.peel2_ch, pyb.Timer.PWM, pin=pyb.Pin(self.peel2_pin))
            self.drive1_pwm = self.timer.channel(self.drive1_ch, pyb.Timer.PWM, pin=pyb.Pin(self.drive1_pin))
            self.drive2_pwm = self.timer.channel(self.drive2_ch, pyb.Timer.PWM, pin=pyb.Pin(self.drive2_pin))
            
            # Set all PWM to 0%
            for pwm in [self.peel1_pwm, self.peel2_pwm, self.drive1_pwm, self.drive2_pwm]:
                pwm.pulse_width_percent(0)
            
            # Setup enable pin
            self.enable_pin = machine.Pin(enable, machine.Pin.OUT_PP)
            self.disable()
            
            self._log("OK - Motors disabled")
            
        except Exception as e:
            self._log(f"ERROR: {e}", force=True)
            raise

    def _log(self, msg, force=False):
        if (self.LOG or force) and self.DMESG:
            self.DMESG.log(f"DRIVES: {msg}")

    def enable(self, state=True):
        """Enable/disable H-bridge output."""
        pin_state = state if not self.enable_invert else not state
        self.enable_pin.value(pin_state)
        self._enabled = state
        self._log(f"{'Enabled' if state else 'Disabled'}")

    def disable(self):
        """Disable H-bridge output."""
        self.enable(False)

    @property
    def enabled(self):
        return self._enabled

    @micropython.native
    def _set_motor_pwm(self, pwm1, pwm2, pwm_min, speed, forward):
        """Set PWM for motor with relative speed mapping. Native: with drive_set()
        this is the last bytecode link in the servo's real-time burst chain
        (update -> _forward_speed -> here, every control tick)."""
        speed = 0 if speed < 0 else (100 if speed > 100 else speed)
        
        # Map relative speed to actual PWM range
        if pwm_min >= 100:
            actual_pwm = 100 if speed > 0 else 0
        else:
            usable_range = 100 - pwm_min
            actual_pwm = pwm_min + (speed / 100.0) * usable_range if usable_range > 0 else 100
        
        actual_pwm = int(max(pwm_min, min(100, actual_pwm)))
        
        if forward:
            pwm1.pulse_width_percent(actual_pwm)
            pwm2.pulse_width_percent(0)
        else:
            pwm1.pulse_width_percent(0)
            pwm2.pulse_width_percent(actual_pwm)

    def peel_set(self, speed, brake=None, absolute_pwm=False):
        """Set peel motor speed (-100 to 100)."""
        if not self.enabled:
            return
        
        # Clamp rather than raise: a stray value must never throw inside the control loop.
        speed = -100 if speed < -100 else (100 if speed > 100 else speed)
        
        brake = self.auto_brake if brake is None else brake
        
        if speed == 0:
            # Both half-bridges high = active brake (short the motor windings). Assumes a
            # driver that reads both-inputs-high as brake, not shoot-through.
            if brake:
                self.peel1_pwm.pulse_width_percent(100)
                self.peel2_pwm.pulse_width_percent(100)
            else:
                self.peel1_pwm.pulse_width_percent(0)
                self.peel2_pwm.pulse_width_percent(0)
        elif absolute_pwm:
            pwm_val = min(100, abs(speed))
            if speed > 0:
                self.peel1_pwm.pulse_width_percent(pwm_val)
                self.peel2_pwm.pulse_width_percent(0)
            else:
                self.peel1_pwm.pulse_width_percent(0)
                self.peel2_pwm.pulse_width_percent(pwm_val)
        else:
            self._set_motor_pwm(self.peel1_pwm, self.peel2_pwm, self.peel_pwm_min, abs(speed), speed > 0)

    @micropython.native
    def drive_set(self, speed, brake=None, absolute_pwm=False):
        """Set drive motor speed (-100 to 100). Native: called once per control tick
        from the servo's real-time burst loop (peel_set is not - it only runs at
        move transitions, so it stays bytecode)."""
        if not self.enabled:
            return
        
        # Clamp rather than raise: a stray value must never throw inside the control loop.
        speed = -100 if speed < -100 else (100 if speed > 100 else speed)
        
        brake = self.auto_brake if brake is None else brake
        
        if speed == 0:
            # Both half-bridges high = active brake (short the motor windings). Assumes a
            # driver that reads both-inputs-high as brake, not shoot-through.
            if brake:
                self.drive1_pwm.pulse_width_percent(100)
                self.drive2_pwm.pulse_width_percent(100)
            else:
                self.drive1_pwm.pulse_width_percent(0)
                self.drive2_pwm.pulse_width_percent(0)
        elif absolute_pwm:
            pwm_val = min(100, abs(speed))
            if speed > 0:
                self.drive1_pwm.pulse_width_percent(pwm_val)
                self.drive2_pwm.pulse_width_percent(0)
            else:
                self.drive1_pwm.pulse_width_percent(0)
                self.drive2_pwm.pulse_width_percent(pwm_val)
        else:
            self._set_motor_pwm(self.drive1_pwm, self.drive2_pwm, self.drive_pwm_min, abs(speed), speed > 0)

