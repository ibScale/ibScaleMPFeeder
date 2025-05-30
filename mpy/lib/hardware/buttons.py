# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# buttons.py - Manages a button state

import machine
import time

class Button:
    def __init__(self, pin_name, active_high=True, debounce_ms=50, double_click_ms=400, 
                 long_press_ms=750, long_press_latch=True, SYSCONFIG=None, DMESG=None, LOG=False):
        self.dmesg = DMESG
        self.pin_name = pin_name
        self.log_debug = LOG or (SYSCONFIG.get('SYSTEM.DEBUG', False) if SYSCONFIG else False)
        
        try:
            self.pin = machine.Pin(pin_name, machine.Pin.IN, 
                                   machine.Pin.PULL_DOWN if active_high else machine.Pin.PULL_UP)
            self._log(f"Init '{pin_name}' (AH={active_high}, DB={debounce_ms}, DC={double_click_ms}, LP={long_press_ms})", force=True)
        except ValueError as e:
            self._log(f"ERROR - Pin '{pin_name}' init failed: {e}", force=True)
            raise

        self.active_high = active_high
        self.debounce_ms, self.dclick_ms, self.lpress_ms = debounce_ms, double_click_ms, long_press_ms
        self.latch = long_press_latch
        
        # State variables
        self.phys_state = self._read()
        self.deb_state = self.phys_state
        self.last_change = time.ticks_ms()
        self.press_time = self.release_time = 0
        self.click_count = 0
        self.lp_pending = self.lp_fired = False
        self.event = None

    def _log(self, msg, force=False):
        if (self.log_debug or force) and self.dmesg:
            self.dmesg.log(f"BTN[{self.pin_name}]: {msg}")

    def _read(self):
        return bool(self.pin.value()) == self.active_high

    def poll(self):
        now = time.ticks_ms()
        new_state = self._read()
        
        # Debounce
        if new_state != self.phys_state:
            self.last_change = now
            self.phys_state = new_state
            
        if time.ticks_diff(now, self.last_change) >= self.debounce_ms:
            if self.deb_state != self.phys_state:
                self.deb_state = self.phys_state
                
                if self.deb_state:  # Pressed
                    self.press_time = now
                    self.lp_pending, self.lp_fired = True, False
                    
                    # Double click check
                    if self.click_count == 1 and time.ticks_diff(now, self.release_time) <= self.dclick_ms:
                        self.click_count = 2
                    else:
                        self.click_count = 1
                        
                else:  # Released
                    self.release_time = now
                    self.lp_pending = False
                    
                    if self.lp_fired:
                        self.event = 'release'
                        self.click_count = 0
                    elif self.click_count == 2:
                        self.event = 'double_click'
                        self.click_count = 0
        
        # Long press check
        if self.deb_state and self.lp_pending and not self.lp_fired:
            if time.ticks_diff(now, self.press_time) >= self.lpress_ms:
                self.event = 'long_press'
                self.lp_fired, self.lp_pending = True, False
                self.click_count = 0
        
        # Single click timeout
        if not self.deb_state and self.click_count == 1:
            if time.ticks_diff(now, self.release_time) > self.dclick_ms:
                self.event = 'click'
                self.click_count = 0

    def get_event(self):
        evt = self.event
        self.event = None
        return evt

    def is_pressed(self):
        return self.deb_state
