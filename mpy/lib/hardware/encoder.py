# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# encoder.py - Uses STM32 hardware quadrature encoder (4x)

import pyb
import machine
import micropython

_DEFAULT_MAX_COUNT = micropython.const(65535)

class Encoder:
    """Hardware quadrature encoder using STM32 Timer peripheral."""

    def __init__(self, timer_num, pin_a_name, pin_b_name, pin_af,
                 max_count=_DEFAULT_MAX_COUNT, invert=False, DMESG=None, LOG=False):

        self.timer_num, self.pin_a_name, self.pin_b_name = timer_num, pin_a_name, pin_b_name
        self.pin_af, self.max_count = pin_af, max_count
        self.invert, self.DMESG, self.LOG = invert, DMESG, LOG

        # State variables
        self._count = self._absolute_count = self._last_count = 0
        self._direction = 0

        self._log(f"Init - Timer: {timer_num}, PinA:'{pin_a_name}', PinB:'{pin_b_name}', AF:{pin_af}, Inv:{invert}", force=True)

        try:
            # Setup pins
            machine.Pin(pin_a_name, machine.Pin.AF_PP, af=pin_af)
            machine.Pin(pin_b_name, machine.Pin.AF_PP, af=pin_af)

            # Setup timer
            self.encoder_timer = pyb.Timer(timer_num, prescaler=0, period=max_count)
            self.encoder_timer.channel(1, pyb.Timer.ENC_AB)

            # Initialize state
            initial_count = self.encoder_timer.counter()
            self._last_count = self._count = self._absolute_count = initial_count

            self._log(f"OK - Initial count: {initial_count}")

        except Exception as e:
            self._log(f"ERROR: {e}", force=True)
            raise

    def _log(self, msg, force=False):
        if (self.LOG or force) and self.DMESG:
            self.DMESG.log(f"ENCODER: {msg}")

    @micropython.native
    def update(self):
        """Update encoder state from the hardware counter (call periodically)."""
        current_count_raw = self.encoder_timer.counter()

        # Calculate delta with wrap-around handling
        delta = current_count_raw - self._last_count
        max_half = self.max_count // 2

        if abs(delta) > max_half:
            delta = delta - (self.max_count + 1) if delta > 0 else delta + (self.max_count + 1)

        if self.invert:
            delta = -delta

        self._absolute_count += delta
        self._direction = 1 if delta > 0 else (-1 if delta < 0 else 0)
        self._count = self._last_count = current_count_raw

    def reset(self):
        """Reset encoder to zero."""
        if hasattr(self, 'encoder_timer'):
            self.encoder_timer.counter(0)
            self._count = self._last_count = self._absolute_count = 0
            self._direction = 0
            self._log("Reset to 0")

    # Properties
    @property
    def count(self): return self._count

    @property
    def absolute_count(self): return self._absolute_count

    @property
    def direction(self): return self._direction
