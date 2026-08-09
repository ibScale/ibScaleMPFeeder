# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# buttons.py - Manages a button state

import machine
import time

class Button:
    def __init__(self, pin_name, active_high=True, debounce_ms=50, double_click_ms=400,
                 long_press_ms=750, SYSCONFIG=None, DMESG=None, LOG=False):
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

        # State variables
        self.phys_state = self._read()
        self.deb_state = self.phys_state
        self.last_change = time.ticks_ms()
        self.press_time = self.release_time = 0
        self.click_count = 0
        self.lp_pending = self.lp_fired = False
        # Small event FIFO: a single slot could drop an event if two land between
        # polls (e.g. long_press then release inside one slow loop iteration).
        self.events = []

        # If the button already reads "pressed" at construction time (e.g. held
        # during boot, or a startup glitch), seed press_time/lp_pending as if a
        # normal press transition had just happened. Without this, deb_state and
        # phys_state start equal, poll()'s transition check never fires for this
        # button, and it gets stuck reporting is_pressed()==True forever with no
        # click/long_press/release event ever generated.
        if self.deb_state:
            self.press_time = self.last_change
            self.lp_pending = True

    def _log(self, msg, force=False):
        if (self.log_debug or force) and self.dmesg:
            self.dmesg.log(f"BTN[{self.pin_name}]: {msg}")

    def _read(self):
        return bool(self.pin.value()) == self.active_high

    def _push(self, evt):
        self.events.append(evt)
        if len(self.events) > 4:
            self.events.pop(0)  # nobody is consuming; keep only the newest few

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
                        self._push('release')
                        self.click_count = 0
                    elif self.click_count == 2:
                        self._push('double_click')
                        self.click_count = 0
        
        # Long press check
        if self.deb_state and self.lp_pending and not self.lp_fired:
            if time.ticks_diff(now, self.press_time) >= self.lpress_ms:
                self._push('long_press')
                self.lp_fired, self.lp_pending = True, False
                self.click_count = 0
        
        # Single click timeout
        if not self.deb_state and self.click_count == 1:
            if time.ticks_diff(now, self.release_time) > self.dclick_ms:
                self._push('click')
                self.click_count = 0

    def get_event(self):
        """Return the oldest unconsumed event (FIFO), or None."""
        return self.events.pop(0) if self.events else None

    def is_pressed(self):
        return self.deb_state
