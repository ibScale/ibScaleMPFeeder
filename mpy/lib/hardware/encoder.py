# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# encoder.py - Uses STM32 hardware quadrature encoder (4x)

import pyb
import time
import micropython

_DEFAULT_MAX_COUNT = micropython.const(65535)

class Encoder:
    """Hardware quadrature encoder using STM32 Timer peripheral."""
    
    def __init__(self, timer_num, pin_a_name, pin_b_name, pin_af, ticks_per_revolution, 
                 max_count=_DEFAULT_MAX_COUNT, invert=False, DMESG=None, LOG=False):
        
        self.timer_num, self.pin_a_name, self.pin_b_name = timer_num, pin_a_name, pin_b_name
        self.pin_af, self.ticks_per_revolution, self.max_count = pin_af, ticks_per_revolution, max_count
        self.invert, self.DMESG, self.LOG = invert, DMESG, LOG
        
        # State variables
        self._count = self._absolute_count = self._last_count = 0
        self._rpm = 0.0
        self._direction = self._delta = 0
        self._last_update_time_ms = 0
        
        if ticks_per_revolution <= 0:
            self._log("WARNING: TICKS_PER_REVOLUTION must be > 0 for RPM calculation", force=True)
        
        self._log(f"Init - Timer: {timer_num}, PinA:'{pin_a_name}', PinB:'{pin_b_name}', AF:{pin_af}, TPR:{ticks_per_revolution}, Inv:{invert}", force=True)
        
        try:
            # Setup pins
            pyb.Pin(pin_a_name, pyb.Pin.AF_PP, af=pin_af)
            pyb.Pin(pin_b_name, pyb.Pin.AF_PP, af=pin_af)
            
            # Setup timer
            self.encoder_timer = pyb.Timer(timer_num, prescaler=0, period=max_count)
            self.encoder_timer.channel(1, pyb.Timer.ENC_AB)
            
            # Initialize state
            initial_count = self.encoder_timer.counter()
            self._last_count = self._count = self._absolute_count = initial_count
            self._last_update_time_ms = time.ticks_ms()
            
            self._log(f"OK - Initial count: {initial_count}")
            
        except Exception as e:
            self._log(f"ERROR: {e}", force=True)
            raise

    def _log(self, msg, force=False):
        if (self.LOG or force) and self.DMESG:
            self.DMESG.log(f"ENCODER: {msg}")

    @micropython.native
    def update(self):
        """Update encoder state - call periodically for accurate RPM."""
        current_time_ms = time.ticks_ms()
        current_count_raw = self.encoder_timer.counter()
        
        # Calculate delta with wrap-around handling
        delta = current_count_raw - self._last_count
        max_half = self.max_count // 2
        
        if abs(delta) > max_half:
            delta = delta - (self.max_count + 1) if delta > 0 else delta + (self.max_count + 1)
        
        if self.invert:
            delta = -delta
        
        # Update state
        self._delta = delta
        self._absolute_count += delta
        self._direction = 1 if delta > 0 else (-1 if delta < 0 else 0)
        
        # Calculate RPM
        time_diff_ms = time.ticks_diff(current_time_ms, self._last_update_time_ms)
        if self.ticks_per_revolution > 0 and time_diff_ms > 0:
            ticks_per_minute = (abs(delta) * 60000.0) / time_diff_ms
            calculated_rpm = ticks_per_minute / self.ticks_per_revolution
            self._rpm = calculated_rpm if delta >= 0 else -calculated_rpm
        else:
            self._rpm = 0.0
        
        # Store for next iteration
        self._count = self._last_count = current_count_raw
        self._last_update_time_ms = current_time_ms

    def reset(self):
        """Reset encoder to zero."""
        if hasattr(self, 'encoder_timer'):
            self.encoder_timer.counter(0)
            self._count = self._last_count = self._absolute_count = 0
            self._last_update_time_ms = time.ticks_ms()
            self._direction = self._delta = 0
            self._rpm = 0.0
            self._log("Reset to 0")

    # Properties
    @property
    def delta(self): return self._delta
    
    @property
    def count(self): return self._count
    
    @property
    def absolute_count(self): return self._absolute_count
    
    @property
    def direction(self): return self._direction
    
    @property
    def rpm(self): return self._rpm
