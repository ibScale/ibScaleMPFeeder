# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# drives.py - Motor controller for DRIVE and PEEL motor

import pyb

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
            self.enable_pin = pyb.Pin(enable, pyb.Pin.OUT_PP)
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

    def _set_motor_pwm(self, pwm1, pwm2, pwm_min, speed, forward):
        """Set PWM for motor with relative speed mapping."""
        if not 0 <= speed <= 100:
            raise ValueError("Speed must be 0-100")
        
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
        
        if not -100 <= speed <= 100:
            raise ValueError("Speed must be -100 to 100")
        
        brake = self.auto_brake if brake is None else brake
        
        if speed == 0:
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

    def drive_set(self, speed, brake=None, absolute_pwm=False):
        """Set drive motor speed (-100 to 100)."""
        if not self.enabled:
            return
        
        if not -100 <= speed <= 100:
            raise ValueError("Speed must be -100 to 100")
        
        brake = self.auto_brake if brake is None else brake
        
        if speed == 0:
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

    def _motor_status(self, pwm1, pwm2):
        """Get motor status from PWM channels."""
        try:
            p1, p2 = pwm1.pulse_width_percent(), pwm2.pulse_width_percent()
            if p1 > 0 and p2 == 0: return "Forward"
            elif p1 == 0 and p2 > 0: return "Reverse"
            elif p1 == 0 and p2 == 0: return "Stop"
            elif p1 >= 99.8 and p2 >= 99.8: return "Brake"
            else: return "Unknown"
        except: return "Error"

    def _motor_speed(self, pwm1, pwm2, pwm_min):
        """Get relative motor speed from PWM channels."""
        status = self._motor_status(pwm1, pwm2)
        if status not in ["Forward", "Reverse"]: return 0
        
        try:
            actual_pwm = pwm1.pulse_width_percent() if status == "Forward" else pwm2.pulse_width_percent()
            if actual_pwm < pwm_min or pwm_min >= 100: return 0
            
            usable_range = 100 - pwm_min
            if usable_range <= 0: return 0
            
            relative_speed = int(round(100.0 * (actual_pwm - pwm_min) / usable_range))
            return relative_speed if status == "Forward" else -relative_speed
        except: return 0

    @property
    def peel_status(self): return self._motor_status(self.peel1_pwm, self.peel2_pwm)
    
    @property
    def peel_get(self): return self._motor_speed(self.peel1_pwm, self.peel2_pwm, self.peel_pwm_min)
    
    @property
    def drive_status(self): return self._motor_status(self.drive1_pwm, self.drive2_pwm)
    
    @property
    def drive_get(self): return self._motor_speed(self.drive1_pwm, self.drive2_pwm, self.drive_pwm_min)

    def deinit(self):
        """Deinitialize timer and pins."""
        self._log("Deinitializing")
        if hasattr(self, 'timer'): self.timer.deinit()
        if hasattr(self, 'enable_pin'): 
            self.disable()
            self.enable_pin.init(pyb.Pin.IN)

