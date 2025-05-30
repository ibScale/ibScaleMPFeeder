# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>
#
# led.py - Manage RGB LED with blinking

import pyb
import math
import time

class RGBLED:
    """
    Controls an RGB LED using the pyb.LED class and its intensity() method.
    Assumes LED objects 1, 2, and 3 correspond to R, G, B.
    Includes timer-based blinking functionality (infinite until stopped),
    blinking between the current color and a specified color.
    """

    # ANSI palette (approximations)
    ANSI_COLORS = {
        'black':        '#000000',
        'red':          '#AA0000',
        'green':        '#00AA00',
        'yellow':       '#AA5500', # Or Amber/Brown/Orange
        'blue':         '#0000AA',
        'magenta':      '#AA00AA',
        'cyan':         '#00AAAA',
        'white':        '#AAAAAA',
        'bright_red':   '#FF5555',
        'bright_green': '#55FF55',
        'bright_yellow':'#FFFF55',
        'bright_blue':  '#5555FF',
        'bright_magenta':'#FF55FF',
        'bright_cyan':  '#55FFFF',
        'bright_white': '#FFFFFF',
    }

    def __init__(self, DMESG=None, REDLED=1, GREENLED=2, BLUELED=3, INVERT=False, ONCOLOR='#FFFFFF', blink_timer_id=2, TEST=False, LOG=False):
        """
        Initializes the RGB LED control using pyb.LED objects.
        Args:
            DMESG: Optional logging object.
            REDLED (int): The ID of the Red LED object (e.g., 1).
            GREENLED (int): The ID of the Green LED object (e.g., 2).
            BLUELED (int): The ID of the Blue LED object (e.g., 3).
            INVERT (bool): Set True if the LED is Common Cathode (intensity needs inversion).
                           False for Common Anode (default).
            ONCOLOR (str): Default 'on' color (hex code or ANSI name). Used by on() if no color specified.
            TEST (bool): If True, perform an ANSI color test upon initialization (blocking).
            blink_timer_id (int): The hardware timer ID to use for blinking. Choose one not used elsewhere.
        """
        self.DMESG = DMESG if DMESG is not None else None
        self.LOG = LOG
        self.ch_r = None
        self.ch_g = None
        self.ch_b = None
        self.invert = INVERT
        self.on_color = ONCOLOR # Store the default 'on' color
        self.current_color = ONCOLOR # Start with LED off logically
        self.blink_timer_id = blink_timer_id # Assignment matches
        self.blink_timer = None
        self.blink_state_on = False # True = blink_color_1, False = blink_color_2
        self.blink_color_1_rgb = (0, 0, 0) # The 'new' color specified in blink()
        self.blink_color_2_rgb = (0, 0, 0) # The color the LED had *before* blink() was called
        self.color_before_blink = '#000000' # Store color before blinking started
        self.blink_count_remaining = 0 # Track remaining blinks for counted blinking
        self.blink_count_total = 0 # Total blinks requested (for logging)

        try:
            self.ch_r = pyb.LED(REDLED)
            self.ch_g = pyb.LED(GREENLED)
            self.ch_b = pyb.LED(BLUELED)
            
            self._log(f"Init - R:{REDLED}, G:{GREENLED}, B:{BLUELED}, Invert:{self.invert}, OnColor:{self.on_color}, Timer:{self.blink_timer_id}", force=True)
            
            # Cycle through primary LED colors to establish state, otherwise the default power-up state could be funky
            for color in ["red", "green", "blue"]:
                self.color(color)
            self.off()
            self.color(self.on_color)

            if TEST:
                self.test()

        except Exception as e:
            self._log(f"Error initializing RGBLED: {e}", force=True)
            self.ch_r = None
            self.ch_g = None
            self.ch_b = None
            self.invert = False

    def _log(self, msg, force=False):
        """Internal logging helper."""
        if (self.LOG or force) and self.DMESG:
            self.DMESG.log(f"LED: {msg}")

    def _hex_to_rgb(self, hex_color):
        """Converts a hex color string (#RRGGBB) or name to an (R, G, B) tuple (0-255)."""
        if isinstance(hex_color, str) and not hex_color.startswith('#'):
            color_lower = hex_color.lower()
            if color_lower in self.ANSI_COLORS:
                hex_color = self.ANSI_COLORS[color_lower]
            else:
                raise ValueError(f"Unknown color name '{hex_color}'")

        if not isinstance(hex_color, str) or not hex_color.startswith('#'):
            raise ValueError(f"Invalid color format '{hex_color}'. Use #RRGGBB or known name.")

        hex_val = hex_color.lstrip('#')
        if len(hex_val) != 6:
            raise ValueError("Invalid hex color format. Use #RRGGBB.")
        try:
            r = int(hex_val[0:2], 16)
            g = int(hex_val[2:4], 16)
            b = int(hex_val[4:6], 16)
            return r, g, b
        except ValueError:
            raise ValueError("Invalid hex characters in color code.")

    def color(self, color_val, set_on_color=False, _is_restore=False):
        """
        Sets the LED color synchronously. Stops any active blinking unless called internally for restore.
        Args:
            color_val (str): Color name (from ANSI palette) or hex code (#RRGGBB).
            set_on_color (bool): Set the ON color to the specified color as well.
            _is_restore (bool): Internal flag used by stop_blink to prevent recursion.
        """
        if not _is_restore and self.blink_timer is not None:
            self._log(f"color('{color_val}') called while blinking. Stopping blink.")
            self.stop_blink()

        if not all([self.ch_r, self.ch_g, self.ch_b]):
            self._log("LED not initialized.")
            return

        hex_code = None
        try:
            ch_r, ch_g, ch_b = self._hex_to_rgb(color_val)

            if isinstance(color_val, str) and not color_val.startswith('#'):
                hex_code = self.ANSI_COLORS.get(color_val.lower())
                if hex_code is None:
                    raise ValueError(f"Internal error resolving color name '{color_val}'")
            else:
                hex_code = color_val

            ch_r = max(0, min(255, ch_r))
            ch_g = max(0, min(255, ch_g))
            ch_b = max(0, min(255, ch_b))

            r_intensity, g_intensity, b_intensity = ch_r, ch_g, ch_b
            if self.invert:
                r_intensity = 255 - ch_r
                g_intensity = 255 - ch_g
                b_intensity = 255 - ch_b

            self.ch_r.intensity(r_intensity)
            self.ch_g.intensity(g_intensity)
            self.ch_b.intensity(b_intensity)

            self.current_color = hex_code

            if set_on_color:
                self.on_color = color_val

        except ValueError as e:
            self._log(f"Error setting color '{color_val}': {e}")
        except Exception as e:
            self._log(f"Unexpected error in color: {e}")

    def off(self):
        """Turns the LED off."""
        self.color('#000000')

    def on(self, color=None):
        """Turns the LED on with specified or default color."""
        self.color(color or self.on_color)

    def test(self, delay_ms=100):
        """
        Perform an ANSI color test, cycling through the ANSI color pallette (blocking).
        Stops any active blinking before starting.
        Args:
            delay_ms (int): Delay between colors in milliseconds.
        """
        self.stop_blink()

        if not all([self.ch_r, self.ch_g, self.ch_b]):
            self._log("Attempted test when LED not initialized.")
            return

        original_color = self.current_color
        self._log("Starting ANSI color test...")
        color_names = list(self.ANSI_COLORS.keys())

        try:
            for color_name in color_names:
                self.color(color_name)
                time.sleep_ms(delay_ms)
            self._log("Test finished. Restoring LED to original color...")
            self.color(original_color)

        finally:
            # Ensure restoration even if interrupted
            self.color(original_color)

    def _blink_callback(self, timer):
        """Internal callback for the blink timer. Runs in interrupt context."""
        try:
            if self.blink_timer is None:
                return

            # If we have a count limit, check if we should stop BEFORE toggling
            if self.blink_count_remaining > 0:
                # If we're about to complete a full blink cycle (going from off to on)
                if not self.blink_state_on:  # Currently showing color_2, about to show color_1
                    self.blink_count_remaining -= 1
                    
                    # If we've completed all blinks, stop immediately
                    if self.blink_count_remaining <= 0:
                        self.blink_timer.deinit()
                        self.blink_timer = None
                        micropython.schedule(self._stop_counted_blink, None)
                        return

            self.blink_state_on = not self.blink_state_on

            if self.blink_state_on:
                r, g, b = self.blink_color_1_rgb
            else:
                r, g, b = self.blink_color_2_rgb

            r_intensity, g_intensity, b_intensity = r, g, b
            if self.invert:
                r_intensity = 255 - r
                g_intensity = 255 - g
                b_intensity = 255 - b

            # Check if channels exist before using intensity (safer in ISR)
            if self.ch_r: self.ch_r.intensity(r_intensity)
            if self.ch_g: self.ch_g.intensity(g_intensity)
            if self.ch_b: self.ch_b.intensity(b_intensity)

        except Exception as e:
            pass # Keep basic ISR error handling

    def _stop_counted_blink(self, _):
        """Helper method called via micropython.schedule to stop counted blink and set on_color."""
        try:
            self._log(f"Completed {self.blink_count_total} blinks. Setting to on_color.")
            # Timer is already stopped, just reset state and set final color
            self.blink_count_remaining = 0
            self.blink_count_total = 0
            self.on()  # Set to on_color
        except Exception as e:
            self._log(f"Error in _stop_counted_blink: {e}")

    def blink(self, blink_color, interval_ms=500, count=None):
        """Starts blinking between blink_color and current color."""
        # Validation
        if not all([self.ch_r, self.ch_g, self.ch_b]) or interval_ms <= 0:
            self._log("Cannot blink: LED not initialized or invalid interval.")
            return

        # Store original state and stop current blink
        original_color_hex = self.current_color
        self.stop_blink()

        # Setup count tracking
        if count is None or count == 0:
            self.blink_count_remaining = 0
            count_msg = "indefinitely"
        else:
            if not isinstance(count, int) or count < 0:
                self._log("Count must be a positive integer, None, or 0.")
                return
            self.blink_count_remaining = count
            self.blink_count_total = count
            count_msg = f"{count} times"

        try:
            # Setup colors
            self.blink_color_1_rgb, _ = self._resolve_color(blink_color)
            try:
                self.blink_color_2_rgb, _ = self._resolve_color(original_color_hex)
            except ValueError:
                self.blink_color_2_rgb = (0, 0, 0)
            
            self.color_before_blink = original_color_hex

            # Start timer
            freq = 1000 / interval_ms
            self._log(f"Blinking {blink_color}↔{original_color_hex}, {interval_ms}ms, {count_msg}")
            
            self.blink_timer = pyb.Timer(self.blink_timer_id, freq=freq)
            self._apply_intensity(*self.blink_color_1_rgb)  # Start with new color
            self.blink_state_on = True
            self.blink_timer.callback(self._blink_callback)

        except Exception as e:
            self._log(f"Error starting blink: {e}")
            if self.blink_timer:
                self.blink_timer.deinit()
            self.blink_timer = None

    def stop_blink(self):
        """Stops the LED blinking and restores the color it had before blinking started."""
        if self.blink_timer:
            timer_was_active = True
            self._log(f"stop_blink: Deinitializing Timer ID {self.blink_timer_id}")
            self.blink_timer.deinit()
            self.blink_timer = None
            # Reset count tracking
            self.blink_count_remaining = 0
            self.blink_count_total = 0
        else:
            timer_was_active = False

        if timer_was_active:
            restore_color = self.color_before_blink if self.color_before_blink else '#000000'
            self.color(restore_color, _is_restore=True)
            self._log(f"Blink stopped. Restored color to {restore_color}.")

    def _resolve_color(self, color_val):
        """Resolves color name or hex to RGB tuple and hex string."""
        if isinstance(color_val, str) and not color_val.startswith('#'):
            color_lower = color_val.lower()
            if color_lower in self.ANSI_COLORS:
                hex_code = self.ANSI_COLORS[color_lower]
                return self._hex_to_rgb(hex_code), hex_code
            else:
                raise ValueError(f"Unknown color name '{color_val}'")
        else:
            return self._hex_to_rgb(color_val), color_val

    def _apply_intensity(self, r, g, b):
        """Apply inversion if needed and set LED intensities."""
        if self.invert:
            r, g, b = 255 - r, 255 - g, 255 - b
        
        if self.ch_r: self.ch_r.intensity(r)
        if self.ch_g: self.ch_g.intensity(g)
        if self.ch_b: self.ch_b.intensity(b)

