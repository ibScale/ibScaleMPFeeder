# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# defaults.py - Default SysConfig for the board hardware and the frozen slushy machine

DEFAULT_SYSCONFIG = {
    "SYSTEM": {
        "UUID": None,
        "SLOTID": 0,  # 0 = Unknown
        "EEPROM_PIN": "ONEWIRE",
        "EEPROM_DRIVER": "DS28E07",  # LumenPNP uses a Maxim DS28E07 by default
        "TICKS_010MM": 22.546,  # How many ticks per 0.10mm
        "SLOT_PROFILE": "normal",  # Speed profile for this slot's parts (gentle/normal/fast)
        "APP": "app.py",  # What to launch after we're done here
        "WATCHDOG_S": 0,  # Hardware watchdog timeout in seconds; 0 = off. Once on it runs until reset (~32s max)
        "DEBUG": False,  # Debug levels of logging. !!! LOTS OF NOISE !!!
    },
    "APP": {
        "LOOP_INTERVAL_MS": 20,  # Main app control loop time
        "TICK_INTERVAL_MS": 5000,  # How often for application tick aka heartbeat
        "GC_INTERVAL_MS": 60000,  # How often to run garbage collection, this is blocking and typically takes 20-25ms, so run sparingly, like 1+ min intervals
    },
    "ADC": {
        "VDDA": 3.3,
        "ADC_BITS": 12,
        "VMONVDC": "VMONVDC",  # VDC input
        "VMONSYS": "VMON10V",  # Buck output
        "VMONSYS_RATIO": 4.0303,  # (R1+R2)/R2, I.E. R1 = 100K, R2 = 33K, so 133000/33000 = 4.0303
        "VMONVDC_RATIO": 7.6667,
    },
    "LED": {
        "REDLED": 1,  # Taken from mpconfigboard.h definitions
        "GREENLED": 2,
        "BLUELED": 3,
        "INVERT": True,  # Common Cathode
        "ONCOLOR": "green",
        "BLINK_TIMER": 2,  # Used for hardware blinking
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
        "TIMER": 3,  # Hardware timer
        "TIMER_AF": 2,  # And encoder alternate function
        "MAX": 65535,  # 16-bit timer is universal
        "INVERT": False,  # Invert direction
    },
    "RS485": {
        "UART_ID": 2,  # Taken from mpconfigboard.h
        "DE_PIN": "RS485DE",
        "BAUDRATE": 57600,  # Default for LumenPNP
        "DATA_BITS": 8,
        "PARITY": None,
        "STOP_BITS": 1,
        "BUFFER_SIZE": 0,  # 0 to calculate based on baud rate, for 57.6K this whould be around 2048 bytes
    },
    "SERVO": {
        "MAX": 80,  # Cruise drive speed; If parts get knocked around or overshoot is consistently too high, lower this
        "CREEP": 15,  # Slow terminal approach speed; Lower = more repeatable stop, too low = stall near target
        "MIN": 5,  # Lowest drive speed that still rotates the motor (floor); Raise if the feeder stalls/skips
        "TOLERANCE": 15,  # Consider the move complete if we're +- this many ticks, too small causes excessive overshoots
        "TAKEUP": 200,  # Ticks to take-up for backlash when reversing
        "ACCEL_TICKS": 200,  # Ramp CREEP up to MAX over this distance at the start of a move (soft start)
        "DECEL_TICKS": 250,  # Ramp MAX down to CREEP over this distance before the final creep
        "CREEP_TICKS": 150,  # Hold CREEP for the final this-many ticks before braking; governs stop repeatability
        "UPDATES": 3,  # Consecutive in-tolerance samples required to confirm the stop
        "STALL_MS": 300,  # Fault if the encoder makes no progress for this long while driving (jam detection)
        "STALL_EPS": 3,  # Minimum ticks of movement counted as "progress" for stall detection
        "MOVE_TIMEOUT_MS": 10000,  # Hard per-move time cap before a timeout fault (backstop)
        "VALIDATE_PITCHES_MM": [
            2,
            4,
            8,
            12,
        ],  # Tape pitches (mm) the auto-tuner validates against
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
        "PEEL_RUN_MS": 1000,  # Minimum time for the peel motor to run to take up slack
        "BRAKE": True,  # True = Brake servo to stop, False = Coast servo to stop
    },
    "BUTTONS": {
        "UP": "BTNUP",  # Pin name for UP button
        "UP_HIGH": False,  # Up button is active low
        "DOWN": "BTNDOWN",  # Pin name for DOWN button
        "DOWN_HIGH": False,  # Down button is active low
        "DEBOUNCE_MS": 50,  # Debounce time in milliseconds
        "DOUBLE_CLICK_MS": 300,  # Max time in ms between clicks for a double click
        "LONG_PRESS_MS": 750,  # Time in ms to hold for a long press
    },
}
