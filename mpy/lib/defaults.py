# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# defaults.py - Default SysConfig for the board hardware and the frozen slushy machine

DEFAULT_SYSCONFIG = {
    'SYSTEM': {
        'UUID': None,
        'SLOTID': 0, # 0 = Unknown
        'EEPROM_PIN': 'ONEWIRE',
        'EEPROM_DRIVER': 'DS28E07', # LumenPNP uses a Maxim DS28E07 by default
        'TICKS_010MM': 22.546, # How many ticks per 0.10mm
        'PEEL_OVERRUN_MS': 1000, # How many ms to run peel motor after drive has stopped
        'FORWARD_MS': 1000, # How many ms for average forward movement
        'BACKWARD_MS': 1500, # How many ms for average backward movement
        'APP': 'app.py', # What to launch after we're done here
        'RUN_APP': False, # Run run_app() from app.py
        'DEBUG': False # Debug levels of logging. !!! LOTS OF NOISE !!!
    },
    'APP': {
        'LOOP_INTERVAL_MS': 20, # Main app control loop time
        'TICK_INTERVAL_MS': 5000, # How often for application tick aka heartbeat
        'GC_INTERVAL_MS': 60000, # How often to run garbage collection, this is blocking and typically takes 20-25ms, so run sparingly, like 1+ min intervals
    },
    'ADC': {
        'VDDA': 3.3,
        'ADC_BITS': 12,
        'VMONVDC': 'VMONVDC', # VDC input
        'VMONSYS': 'VMON10V', # Buck output
        'VMONSYS_RATIO': 4.0303, # (R1+R2)/R2, I.E. R1 = 100K, R2 = 33K, so 133000/33000 = 4.0303
        'VMONVDC_RATIO': 7.6667
    },
    'LED': {
        'REDLED': 1, # Taken from mpconfigboard.h definitions
        'GREENLED': 2,
        'BLUELED': 3,
        'INVERT': True, # Common Cathode
        'ONCOLOR': 'green',
        'BLINK_TIMER': 2, # Used for hardware blinking
        'TEST': False, # Perform ANSI color test
    },
    'DRIVES': {
        'DRIVE_INVERT': False, # Set if the motor is spinning in the wrong direction
        'PEEL_INVERT': False, # Ditto, but for peel motor
        'ENABLE_INVERT': False, # Set if enable is active LOW
        'PEEL1_PIN': 'PEEL1', # Taken from pins.csv
        'PEEL2_PIN': 'PEEL2',
        'DRIVE1_PIN': 'DRIVE1',
        'DRIVE2_PIN': 'DRIVE2',
        'ENABLE_PIN': 'DRIVEENABLE',
        'TIMER_ID': 4, # Match timer and frequency from mpconfigboard.h
        'PWM_FREQUENCY': 25000,
        'PEEL1_CH': 1,
        'PEEL2_CH': 2,
        'DRIVE1_CH': 3,
        'DRIVE2_CH': 4,
        'DRIVE_PWM_MIN': 65, # Minimum PWM it takes to get the motor to still freewheel without stalling
        'PEEL_PWM_MIN': 65,
        'AUTOBRAKE': True, # Brake instead of stop/coast when speed set to 0
    },
    'ENCODER': {
        'PINA': 'DRIVEENCA', # Pins are the same
        'PINB': 'DRIVEENCB',
        'TIMER': 3, # Hardware timer
        'TIMER_AF': 2, # And encoder alternate function
        'TPR': 28, # Ticks per revolution per pin (A or B); Include decoding multipliers
        'MAX': 65535, # 16-bit timer is universal
        'INVERT': False, # Invert direction
    },
    'RS485': {
        'UART_ID': 2, # Taken from mpconfigboard.h
        'DE_PIN': 'RS485DE',
        'BAUDRATE': 57600, # Default for LumenPNP
        'DATA_BITS': 8,
        'PARITY': None,
        'STOP_BITS': 1,
        'BUFFER_SIZE': 0, # 0 to calculate based on baud rate, for 57.6K this whould be around 2048 bytes
    },
    'SERVO': {
        'MAX': 80, # Max drive speed; If parts get knocked around or overshoot is consistently too high, lower this
        'MIN': 5, # Min drive speed; If the feeder stalls or skips increase this
        'TOLERANCE': 15, # Consider the move complete if we're +- this many ticks, too small causes excessive overshoots
        'TAKEUP': 200, # Ticks to take-up for backlash when reversing
        'RAMP_TICKS': 250, # Endpoint for trajectory ramp; Switch to PID control once within this many ticks of requested endpoint
        'RAMP_TAPER': 20, # Percentage of MAX speed for trajectory ramp endpoint; I.E. if MAX = 80 and TAPER = 20, then the ramp will taper down to 16 at it's endpoint before switching to PID control
        'P': 0.05, # Proportional
        'I': 0.0055, # Integral
        'D': 0.001, # Deviation
        'PID_TAPER': 30, # Limit output speed at final set point
        'UPDATES': 3, # How many update cycles to allow encoder to settle and endpoints
        'PEEL_ENABLE': True, # Run the peel motor with the servo
        'PEEL_SPEED': 100,
        'PEEL_RUN_MS': 1000, # Minimum time for the peel motor to run to take up slack
        'BRAKE': True, # True = Brake servo to stop, False = Coast servo to stop
    },
    'BUTTONS': {
        'UP': 'BTNUP',          # Pin name for UP button
        'UP_HIGH': False,       # Up button is active low
        'DOWN': 'BTNDOWN',      # Pin name for DOWN button
        'DOWN_HIGH': False,     # Down button is active low
        'DEBOUNCE_MS': 50,      # Debounce time in milliseconds
        'DOUBLE_CLICK_MS': 300, # Max time in ms between clicks for a double click
        'LONG_PRESS_MS': 750,   # Time in ms to hold for a long press
        'LONG_PRESS_LATCH': True # When a long press is detected, latch until the input changes state
    }
}