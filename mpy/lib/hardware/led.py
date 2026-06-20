# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>
#
# led.py - RGB status LED on three PWM channels, with timer-driven blink.

import pyb
import micropython
import time

# The 16 standard ANSI/VGA colors as (R, G, B) 0-255 (common-anode levels; INVERT flips
# for common cathode). Plus 'off' as an alias for black. Note the VGA quirk that dim
# 'yellow' is amber/brown - 'bright_yellow' is the pure yellow.
COLORS = {
    'off':            (0, 0, 0),     # alias for black
    'black':          (0, 0, 0),
    'red':            (170, 0, 0),
    'green':          (0, 170, 0),
    'yellow':         (170, 85, 0),
    'blue':           (0, 0, 170),
    'magenta':        (170, 0, 170),
    'cyan':           (0, 170, 170),
    'white':          (170, 170, 170),
    'bright_black':   (85, 85, 85),
    'bright_red':     (255, 85, 85),
    'bright_green':   (85, 255, 85),
    'bright_yellow':  (255, 255, 85),
    'bright_blue':    (85, 85, 255),
    'bright_magenta': (255, 85, 255),
    'bright_cyan':    (85, 255, 255),
    'bright_white':   (255, 255, 255),
}


class RGBLED:
    """RGB status LED over three pyb.LED PWM channels, with non-blocking blink.

    Colors are referenced by name (see COLORS); intensity() drives each channel's PWM.
    Set INVERT=True for a common-cathode LED (duty is inverted). Blink runs on a hardware
    Timer; a counted blink returns to the on-color when it finishes, an indefinite blink
    restores the pre-blink color when stopped.
    """

    def __init__(self, DMESG=None, REDLED=1, GREENLED=2, BLUELED=3, INVERT=False,
                 ONCOLOR='green', blink_timer_id=2, LOG=False):
        self.DMESG, self.LOG, self.invert = DMESG, LOG, INVERT
        self.on_color = ONCOLOR if ONCOLOR in COLORS else 'white'
        self.blink_timer_id = blink_timer_id
        self.ch = None
        self._current = 'off'
        self._timer = None
        self._blink_rgb = (0, 0, 0)   # color shown on the "on" half of a blink
        self._base_rgb = (0, 0, 0)    # color restored when the blink stops
        self._blink_on = False
        self._count = 0               # remaining blink cycles (0 = forever)

        try:
            self.ch = (pyb.LED(REDLED), pyb.LED(GREENLED), pyb.LED(BLUELED))
        except Exception as e:
            self._log(f"Init failed: {e}", force=True)
            return
        self._log(f"Init - R/G/B:{REDLED}/{GREENLED}/{BLUELED}, Invert:{INVERT}, OnColor:{self.on_color}, Timer:{blink_timer_id}", force=True)
        self.color(self.on_color)

    def _log(self, msg, force=False):
        if (self.LOG or force) and self.DMESG:
            self.DMESG.log(f"LED: {msg}")

    def _set(self, rgb):
        """Write an (r, g, b) tuple to the channels. Allocation-free, so ISR-safe."""
        if self.ch:
            r, g, b = rgb
            if self.invert:
                r, g, b = 255 - r, 255 - g, 255 - b
            self.ch[0].intensity(r)
            self.ch[1].intensity(g)
            self.ch[2].intensity(b)

    def color(self, name):
        """Set a solid color by name; stops any active blink."""
        if self._timer:
            self.stop_blink()
        rgb = COLORS.get(name)
        if rgb is None:
            self._log(f"Unknown color '{name}'")
            return
        self._current = name
        self._set(rgb)

    def off(self):
        self.color('off')

    def on(self, name=None):
        self.color(name or self.on_color)

    def blink(self, name, interval_ms=500, count=None):
        """Blink between `name` and the current color. count=None/0 blinks forever."""
        rgb = COLORS.get(name)
        if not self.ch or interval_ms <= 0 or rgb is None:
            if rgb is None:
                self._log(f"Unknown color '{name}'")
            return
        self.stop_blink()
        self._base_rgb = COLORS.get(self._current, (0, 0, 0))
        self._blink_rgb = rgb
        self._count = count if (count and count > 0) else 0
        self._blink_on = True
        self._set(rgb)
        try:
            self._timer = pyb.Timer(self.blink_timer_id, freq=1000 / interval_ms)
            self._timer.callback(self._tick)
        except Exception as e:
            self._timer = None
            self._log(f"Blink failed: {e}", force=True)

    def _tick(self, _t):
        # Hard timer IRQ: keep allocation-free. Toggle blink color <-> base color.
        if self._timer is None:
            return
        if self._count and not self._blink_on:   # about to begin another cycle
            self._count -= 1
            if self._count <= 0:
                self._timer.deinit()
                self._timer = None
                micropython.schedule(self._blink_done, None)
                return
        self._blink_on = not self._blink_on
        self._set(self._blink_rgb if self._blink_on else self._base_rgb)

    def _blink_done(self, _):
        self.on()   # counted blink finished -> back to the on-color

    def stop_blink(self):
        """Stop blinking and restore the pre-blink color."""
        if self._timer:
            self._timer.deinit()
            self._timer = None
            self._count = 0
            self._set(self._base_rgb)

    def test(self, delay_ms=150):
        """Cycle through the palette for a visual check (blocking)."""
        self.stop_blink()
        for name in COLORS:
            self.color(name)
            time.sleep_ms(delay_ms)
        self.color(self.on_color)
