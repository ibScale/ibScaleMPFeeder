# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# defaults.py - Default SysConfig for the board hardware and the frozen slushy machine

DEFAULT_SYSCONFIG = {
    "SYSTEM": {
        "UUID": None,
        "SLOT_ID": 255,  # 255 = Unprogrammed (answers broadcast only, like the reference firmware; 0 is the LumenPNP host, 1-254 are valid slot IDs)
        "SLOT_OVERRIDE": False, # Ignore EEPROM and advertise as SLOT_ID
        "EEPROM_PIN": "ONEWIRE",
        "EEPROM_DRIVER": "DS28E07",  # LumenPNP uses a Maxim DS28E07 by default
        "TICKS_010MM": 22.546,  # How many encoder ticks per 0.10mm linear movement
        "APP": "app.py",  # What to launch after we're done here
        "WATCHDOG_S": 0,  # Hardware watchdog timeout in seconds; 0 = off, once activated it must be fed every `WATCHDOG_S` seconds or it will reset.
        "DEBUG": False,  # Debug levels of logging. !!! LOTS OF NOISE !!!
        "TEMP_MAX_C": 70,  # LED turns solid red + FAULT logged if MCU temp reaches/exceeds this
    },
    "APP": {
        "SLOT_PROFILE": "normal",  # Speed profile for this slot's parts (gentle/normal/fast)
        "JOG_MM": 2,   # Default jog size in mm for button click; 2mm in Photon
        "LOOP_INTERVAL_MS": 20,  # Main app control loop time
        "TICK_INTERVAL_MS": 5000,  # How often for application tick aka heartbeat
        "GC_INTERVAL_MS": 60000,  # How often to run garbage collection, this is blocking and typically takes 20-25ms, so run sparingly, like 1+ min intervals
    },
    "ADC": {
        "VDDA": 3.3,
        "ADC_BITS": 12,
        "VMONVDC": "VMONVDC",  # VDC input (ADC1_IN8 / connector Pin 18) - nominal 24V
        "VMONSYS": "VMON10V",  # Buck output (ADC1_IN9 / connector Pin 19) - nominal 10V, regulated
        "VMONSYS_RATIO": 4.0303,  # (R1+R2)/R2, I.E. R1 = 100K, R2 = 33K, so 133000/33000 = 4.0303
        "VMONVDC_RATIO": 7.6667,
        "VDC_MIN": 20.0,  # Fault (LED red) if VDC falls below this (nominal 24V input)
        "VDC_MAX": 28.0,  # Fault if VDC exceeds this
        "VSYS_MIN": 9.0,  # Fault if VSYS (regulated 10V buck) falls below this
        "VSYS_MAX": 11.0,  # Fault if VSYS exceeds this
    },
    "LED": {
        "REDPIN": "LEDRED",  # Taken from pins.csv
        "GREENPIN": "LEDGREEN",
        "BLUEPIN": "LEDBLUE",
        "TIMER_ID": 1,  # TIM1 - matches mpconfigboard.h MICROPY_HW_LEDx_PWM
        "PWM_FREQUENCY": 1000,
        "RED_CH": 1,
        "GREEN_CH": 2,
        "BLUE_CH": 3,
        "INVERT": True,  # Common Cathode
        # Which physical channel (0=RED_CH/REDPIN, 1=GREEN_CH/GREENPIN, 2=BLUE_CH/BLUEPIN)
        # actually lights which color, as an 'R'/'G'/'B' per position. Some boards have
        # the die color order swapped vs. the pin names; run the console's calibration
        # (option 1 -> LED wiring calibration) to determine this rather than guessing.
        "CHANNEL_COLORS": ["R", "G", "B"],
        # Status -> color policy (names from led.py COLORS or '#RRGGBB' hex). All
        # code sets LED state by name (LED.state('fault')); re-theme it here.
        "STATES": {
            "boot": "#800080",
            "waiting": "yellow",
            "ready": "green",
            "feeding": "cyan",
            "identify": "blue",
            "fault": "red",
            "stopped": "yellow",
        },
    },
    "DRIVES": {
        "DRIVE_INVERT": False,  # Set if the motor is spinning in the wrong direction
        "PEEL_INVERT": False,  # Ditto, but for peel motor
        "ENABLE_INVERT": False,  # Set if enable is active LOW
        "PEEL1_PIN": "PEEL1",  # Taken from pins.csv
        "PEEL2_PIN": "PEEL2",
        "DRIVE1_PIN": "DRIVE1",
        "DRIVE2_PIN": "DRIVE2",
        "ENABLE_PIN": "DRIVEENABLE",
        "TIMER_ID": 4,  # Match timer and frequency from mpconfigboard.h
        "PWM_FREQUENCY": 25000,
        "PEEL1_CH": 1,
        "PEEL2_CH": 2,
        "DRIVE1_CH": 3,
        "DRIVE2_CH": 4,
        "DRIVE_PWM_MIN": 65,  # Minimum PWM it takes to get the motor to still freewheel without stalling
        "PEEL_PWM_MIN": 65,
        "AUTOBRAKE": True,  # Brake instead of stop/coast when speed set to 0
    },
    "ENCODER": {
        "PINA": "DRIVEENCA",  # Pins are the same
        "PINB": "DRIVEENCB",
        "TIMER": 3,  # 16-bit Hardware timer
        "TIMER_AF": 2,  # Hardware encoder alternate function
        "MAX": 65535,  # 16-bit timer, must match hardware timer used
        "INVERT": False,  # Invert direction
    },
    "RS485": {
        "UART_ID": 2,  # Taken from mpconfigboard.h
        "DE_PIN": "RS485DE",
        "BAUDRATE": 57600,  # Default for LumenPNP
        "DATA_BITS": 8,
        "PARITY": None,
        "STOP_BITS": 1,
        "MAX_CHUNKS": 16,  # RX queue depth (bursts); bounds buffering while a move blocks the loop
    },
    "SERVO": {
        "MAX": 80,  # Cruise drive speed; If parts get knocked around or overshoot is consistently too high, lower this
        "CREEP": 15,  # Slow terminal approach speed; Lower = more repeatable stop, too low = stall near target
        "MIN": 5,  # Lowest drive speed that still rotates the motor (floor); Raise if the feeder stalls/skips
        "KICK": 60,  # Breakaway duty floor while an approach hasn't moved yet (overcomes stiction); 0 disables
        "KICK_TICKS": 5,  # Travel (ticks) that counts as broken away; the kick ends the moment this is reached
        "KICK_MS": 100,  # Kick time budget per approach; a hard jam then drops to normal duty until the stall fault
        "TOLERANCE": 15,  # Consider the move complete if we're +- this many ticks, too small causes excessive overshoots
        "TAKEUP": 200,  # Ticks to take-up for backlash when reversing
        "ACCEL_TICKS": 200,  # Ramp CREEP up to MAX over this distance at the start of a move (soft start)
        "DECEL_TICKS": 250,  # Ramp MAX down to CREEP over this distance before the final creep
        "CREEP_TICKS": 150,  # Hold CREEP for the final this-many ticks before braking; governs stop repeatability
        "UPDATES": 3,  # Consecutive in-tolerance samples required to confirm the stop
        "STALL_MS": 300,  # Fault if the encoder makes no progress for this long while driving (jam detection)
        "STALL_EPS": 3,  # Minimum ticks of movement counted as "progress" for stall detection
        "MOVE_TIMEOUT_MS": 10000,  # Hard per-move time cap before a timeout fault (backstop)
        # Per-move speed profiles scale MAX and ACCEL_TICKS. The creep tail (CREEP/CREEP_TICKS)
        # is shared, so stop accuracy is identical across profiles - only speed/gentleness change.
        # Pick per part at the caller (gentle for light parts/shallow pockets, fast for robust ones).
        "PROFILES": {
            "gentle": {"MAX_SCALE": 0.5, "ACCEL_SCALE": 2.0},  # Slow peak, soft accel
            "normal": {"MAX_SCALE": 1.0, "ACCEL_SCALE": 1.0},
            "fast": {"MAX_SCALE": 1.0, "ACCEL_SCALE": 0.5},  # Full peak, snappy accel
        },
        "PEEL_ENABLE": True,  # Run the peel motor with the servo
        "PEEL_SPEED": 100,
        "POST_PEEL_MS": 200,  # Keep the peel motor running this long after the drive move finishes
        "BRAKE": True,  # True = Brake servo to stop, False = Coast servo to stop
    },
    "BUTTONS": {
        "UP": "BTNUP",  # Pin name for UP button
        "UP_INVERT": True,  # Set if the button is active low (pressed = pin reads low)
        "DOWN": "BTNDOWN",  # Pin name for DOWN button
        "DOWN_INVERT": True,  # Ditto, but for DOWN button
        "DEBOUNCE_MS": 50,  # Debounce time in milliseconds
        "DOUBLE_CLICK_MS": 300,  # Max time in ms between clicks for a double click
        "LONG_PRESS_MS": 750,  # Time in ms to hold for a long press
    },
}
