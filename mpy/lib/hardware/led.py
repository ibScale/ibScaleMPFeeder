# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>
#
# led.py - RGB status LED on three PWM channels, with event-loop-driven blink.

import pyb
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


# Status-name -> color policy, overridable via LED.STATES in sysconfig. This is the
# single place the "what color means what" decision lives; callers say
# LED.state('fault') etc. and never hard-code colors, so re-theming or swapping the
# indicator hardware touches only this map / this file.
_DEFAULT_STATES = {
    'boot': '#800080',      # power-up until the application takes over (purple)
    'waiting': 'yellow',    # app running, Photon not initialized by a host yet
    'ready': 'green',       # initialized / manual mode ready
    'feeding': 'cyan',      # move in progress
    'identify': 'blue',     # host-requested identify flash
    'fault': 'red',         # stall/timeout/overtemp/voltage fault
    'stopped': 'yellow',    # application halted (e.g. dropped to REPL)
}


def _resolve(name):
    """Resolve a color name (see COLORS) or a HEX/HTML color code - '#RGB' or
    '#RRGGBB', case-insensitive - to an (r, g, b) 0-255 tuple. Returns None if `name`
    is neither a recognized color name nor a validly-formed hex code."""
    if isinstance(name, str) and name.startswith('#'):
        hexstr = name[1:]
        if len(hexstr) == 3:
            hexstr = ''.join(c * 2 for c in hexstr)
        if len(hexstr) != 6:
            return None
        try:
            return (int(hexstr[0:2], 16), int(hexstr[2:4], 16), int(hexstr[4:6], 16))
        except ValueError:
            return None
    return COLORS.get(name)


class RGBLED:
    """RGB status LED over three hardware-timer PWM channels, with non-blocking, event-loop-driven blink.

    Drives TIM(x) channels directly via pyb.Timer (same pattern as hardware/drives.py)
    rather than pyb.LED. pyb.LED.intensity() only uses real PWM for values strictly
    between 0 and 255 - exact 0/255 fall back to a hard digital on/off and, if that
    channel had PWM running, tear the pin back out of alternate-function mode. On this
    board that left the (non-boundary) mid-range PWM values it actually needs - like the
    inverted green channel at boot - dead until something later happened to nudge it
    into working, showing the LED unlit at power-up until, e.g., a full color-cycle
    test managed to leave it running. Driving the timer/channels ourselves gives
    continuous PWM across the whole 0-255 range with no digital fallback.

    Colors are referenced either by name (see COLORS) or as a HEX/HTML color code -
    '#RGB' or '#RRGGBB', case-insensitive (e.g. '#0f0' or '#00FF00' for green) - anywhere
    a color name is accepted (color(), and by extension whatever blink() is currently
    showing).

    Deliberately minimal, two-verb interface:
      - color(name) sets the solid/resting color. Callers never need to save or restore
        a previous color themselves when they're done with a temporary color (e.g. cyan
        during a move, red for a fault, blue for identify) - they just remember whatever
        current_color was beforehand and call color() again with that name once they're
        done. Since these overrides are always started and finished within a single,
        well-defined stretch of code (a blocking move, a fault condition, a timed
        identify flash), that simple "remember and restore" pattern nests correctly on
        its own without this class needing to track a stack of prior states.
      - blink(interval_ms) blinks the *current* color (whatever color() last set) on/off
        at interval_ms; blink(0) stops blinking and shows the current color solid again.
        Blinking never changes what color() is - it's a toggle overlaid on top of it, so
        a caller can freely call color() while blinking is active (e.g. a fault turning
        the LED red while the console-open blink is active) and it keeps blinking, just
        with the new color.

    Non-blocking; poll() must be called every main-loop iteration (~20ms) to advance an
    active blink.
    """

    def __init__(self, DMESG=None, REDPIN='LEDRED', GREENPIN='LEDGREEN', BLUEPIN='LEDBLUE',
                 TIMER_ID=1, PWM_FREQUENCY=1000, RED_CH=1, GREEN_CH=2, BLUE_CH=3,
                 INVERT=False, CHANNEL_COLORS=None, STATES=None, LOG=False):
        self.DMESG, self.LOG, self.invert = DMESG, LOG, INVERT
        self._states = dict(_DEFAULT_STATES)
        if STATES:
            self._states.update(STATES)
        # Physical channel index (0=RED_CH, 1=GREEN_CH, 2=BLUE_CH) -> the color it
        # actually emits. Defaults to the pin names being trustworthy; calibration
        # (console -> option 1) overwrites this via set_channel_map() once the real
        # wiring on a given board is known.
        if CHANNEL_COLORS and sorted(CHANNEL_COLORS) == ['B', 'G', 'R']:
            self._channel_map = list(CHANNEL_COLORS)
        else:
            self._channel_map = ['R', 'G', 'B']
        self.ch = None
        self.period = 0
        self._current = 'off'
        self._blinking = False
        self._blink_on = False
        self._interval_ms = 0
        self._next_tick = 0

        try:
            self.pwm_timer = pyb.Timer(TIMER_ID, freq=PWM_FREQUENCY)
            self.period = self.pwm_timer.period()
            self.ch = (
                self.pwm_timer.channel(RED_CH, pyb.Timer.PWM, pin=pyb.Pin(REDPIN)),
                self.pwm_timer.channel(GREEN_CH, pyb.Timer.PWM, pin=pyb.Pin(GREENPIN)),
                self.pwm_timer.channel(BLUE_CH, pyb.Timer.PWM, pin=pyb.Pin(BLUEPIN)),
            )
        except Exception as e:
            self._log(f"Init failed: {e}", force=True)
            return
        self._log(f"Init - R/G/B:{REDPIN}/{GREENPIN}/{BLUEPIN}, Timer:{TIMER_ID}@{PWM_FREQUENCY}Hz " +
                  f"(period={self.period}), Invert:{INVERT}", force=True)
        # Boot default (purple unless re-themed), so it's visually obvious the
        # application hasn't taken over yet.
        self.state('boot')

    def _log(self, msg, force=False):
        if (self.LOG or force) and self.DMESG:
            self.DMESG.log(f"LED: {msg}")

    def _set(self, rgb):
        """Write an (r, g, b) tuple to the channels, routed through the channel map
        (physical channel index -> color it actually emits; see CHANNEL_COLORS)."""
        if self.ch:
            r, g, b = rgb
            if self.invert:
                r, g, b = 255 - r, 255 - g, 255 - b
            period = self.period
            values = {'R': r, 'G': g, 'B': b}
            for i, color in enumerate(self._channel_map):
                self.ch[i].pulse_width(values[color] * period // 255)

    def color(self, name):
        """Set the solid/resting color, by name (see COLORS) or as a HEX/HTML color
        code ('#RGB' or '#RRGGBB'). If a blink is currently active, it keeps blinking -
        just with this new color from here on - rather than being interrupted."""
        rgb = _resolve(name)
        if rgb is None:
            self._log(f"Unknown color '{name}'")
            return
        self._current = name
        if not self._blinking:
            self._set(rgb)

    def state(self, name):
        """Set the color mapped to a named status (see _DEFAULT_STATES / LED.STATES
        in sysconfig). Unknown names fall through to color(), so a raw color name
        or hex code also works here."""
        self.color(self._states.get(name, name))

    @property
    def current_color(self):
        """Name of the color currently set via color() (regardless of blink state)."""
        return self._current

    def blink(self, interval_ms=500):
        """Blink the current color on/off at interval_ms, forever, until blink(0) is
        called. blink(0) stops blinking and shows the current color solid.

        Non-blocking; actual toggling happens in poll(), called from the main loop.
        """
        if interval_ms <= 0:
            self._blinking = False
            self._set(_resolve(self._current) or (0, 0, 0))
            return
        self._blinking = True
        self._blink_on = True
        self._interval_ms = interval_ms
        self._set(_resolve(self._current) or (0, 0, 0))
        self._next_tick = time.ticks_add(time.ticks_ms(), interval_ms)

    def poll(self):
        """Advance an active blink. Call once per main-loop iteration (~20ms)."""
        if not self._blinking:
            return
        now = time.ticks_ms()
        if time.ticks_diff(now, self._next_tick) < 0:
            return
        self._next_tick = time.ticks_add(self._next_tick, self._interval_ms)
        self._blink_on = not self._blink_on
        self._set(_resolve(self._current) or (0, 0, 0) if self._blink_on else (0, 0, 0))

    def set_invert(self, invert):
        """Override the common-anode/common-cathode polarity flag. Used by calibration
        once the real polarity has been confirmed against the physical LED."""
        self.invert = bool(invert)

    def set_channel_map(self, mapping):
        """Override the physical-channel-index -> color map (see CHANNEL_COLORS). Used
        by calibration once the real per-channel wiring has been confirmed."""
        self._channel_map = list(mapping)

    def probe(self, index=None):
        """Drive physical channel `index` (0=RED_CH, 1=GREEN_CH, 2=BLUE_CH) to its 'on'
        level for the current invert setting, all other channels 'off'; index=None
        drives every channel 'off'. Bypasses color()/the channel map entirely - for
        calibration to identify raw wiring (polarity, and which channel lights which
        color) before either is known or trusted."""
        if not self.ch:
            return
        self._blinking = False
        on_level = 0 if self.invert else 255
        off_level = 255 if self.invert else 0
        period = self.period
        for i, ch in enumerate(self.ch):
            level = on_level if i == index else off_level
            ch.pulse_width(level * period // 255)

    def test(self, delay_ms=150):
        """Cycle through the palette for a visual check (blocking)."""
        self.blink(0)
        for name in COLORS:
            self.color(name)
            time.sleep_ms(delay_ms)
        self.color('green')
