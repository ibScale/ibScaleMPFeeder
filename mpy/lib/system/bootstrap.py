# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# bootstrap.py - Initializes the hardware and environment so the application doesn't have to

import os, pyb, gc
from util.misc import vfs_info, get_uuid

def _log(DMESG, msg, force=False, debug_mode=False):
    """Bootstrap logging function."""
    if (debug_mode or force) and DMESG:
        if force:
            # Normal system messages without BOOTSTRAP prefix
            DMESG.log(msg)
        else:
            DMESG.log(f"BOOTSTRAP: {msg}")

def _log_system_info(DMESG):
    """Logs OS and VFS information."""
    try:
        uname = os.uname()
        _log(DMESG, f"Micropython: {uname.version} ({uname.release})", force=True)
        _log(DMESG, f"Platform: {uname.machine}", force=True)
        _log(DMESG, f"SysName: {uname.sysname}", force=True)
    except Exception as e:
        _log(DMESG, f"ERROR reading OS info: {e}", force=True)

    try:
        blocks, free_blocks, block_size, size_mb, free_mb = vfs_info('/flash')
        used_blocks, used_mb = blocks - free_blocks, size_mb - free_mb
        _log(DMESG, f"VFS: '/flash' - BlkSize={block_size}, Used={used_blocks}/{blocks} blks ({used_mb:.2f}MB), Total={size_mb:.2f}MB, Free={free_mb:.2f}MB", force=True)
    except Exception as e:
        _log(DMESG, f"ERROR reading VFS info: {e}", force=True)

def _setup_identity(DMESG, SYSCONFIG, LOG, app_passthrough):
    """Sets UUID and reads Slot ID from EEPROM."""
    debug_mode = SYSCONFIG.get('SYSTEM.DEBUG', False)
    
    # Set UUID
    try:
        uuid_str = get_uuid()
        _log(DMESG, f"UUID: {uuid_str}", force=True)
        SYSCONFIG.set('SYSTEM.UUID', uuid_str)
    except Exception as e:
        _log(DMESG, f"ERROR setting UUID: {e}", force=True)

    # Initialize EEPROM if configured and read Slot ID
    slot_id = 0
    eeprom_pin = SYSCONFIG.get('SYSTEM.EEPROM_PIN')
    if not eeprom_pin:
        _log(DMESG, f"EEPROM: No pin configured - Using Slot ID {slot_id}", force=True)
        SYSCONFIG.set('SYSTEM.SLOTID', slot_id)
        return

    try:
        _log(DMESG, "Initializing EEPROM...", debug_mode=debug_mode)
        from hardware.eeprom import EEPROM
        eeprom_driver = SYSCONFIG.get('SYSTEM.EEPROM_DRIVER', 'DS28E07')
        eeprom = EEPROM(eeprom_pin, driver=eeprom_driver, DMESG=DMESG, LOG=debug_mode)
        app_passthrough['EEPROM'] = eeprom
        
        # Read Slot ID from EEPROM
        slot_data = eeprom.read_memory(0, 1)
        if slot_data and len(slot_data) == 1:
            slot_id = int(slot_data[0])
            _log(DMESG, f"EEPROM: Read Slot ID {slot_id} from device", force=True)
        else:
            _log(DMESG, f"EEPROM: No valid Slot ID found - Using default {slot_id}", force=True)
    except Exception as e:
        _log(DMESG, f"EEPROM: Error accessing device ({e}) - Using default Slot ID {slot_id}", force=True)

    SYSCONFIG.set('SYSTEM.SLOTID', slot_id)
    _log(DMESG, f"Using Slot ID: {slot_id}")

def _initialize_hardware(DMESG, SYSCONFIG, app_passthrough, LOG):
    """Initializes hardware components."""
    debug_mode = SYSCONFIG.get('SYSTEM.DEBUG', False)

    # Buttons
    try:
        _log(DMESG, "Initializing buttons...", debug_mode=debug_mode)
        from hardware.buttons import Button
        btn_cfg = SYSCONFIG.get('BUTTONS')
        for btn_name, pin_key, high_key in [('BTNUP', 'UP', 'UP_HIGH'), ('BTNDOWN', 'DOWN', 'DOWN_HIGH')]:
            app_passthrough[btn_name] = Button(
                pin_name=btn_cfg[pin_key], active_high=btn_cfg[high_key],
                debounce_ms=btn_cfg['DEBOUNCE_MS'], double_click_ms=btn_cfg['DOUBLE_CLICK_MS'],
                long_press_ms=btn_cfg['LONG_PRESS_MS'], long_press_latch=btn_cfg['LONG_PRESS_LATCH'],
                SYSCONFIG=SYSCONFIG, DMESG=DMESG
            )
    except Exception as e:
        _log(DMESG, f"CRITICAL ERROR initializing buttons: {e}", force=True)
        raise

    # ADC
    try:
        _log(DMESG, "Initializing ADC...", debug_mode=debug_mode)
        from hardware.adc import ADCReader
        adc_cfg = SYSCONFIG.get('ADC')
        app_passthrough['ADC'] = ADCReader(
            DMESG=DMESG, VDDA=adc_cfg['VDDA'], VMONVDC_PIN=adc_cfg['VMONVDC'],
            VMONSYS_PIN=adc_cfg['VMONSYS'], ADC_BITS=adc_cfg['ADC_BITS'],
            VMONSYS_RATIO=adc_cfg['VMONSYS_RATIO'], VMONVDC_RATIO=adc_cfg['VMONVDC_RATIO']
        )
    except Exception as e:
        _log(DMESG, f"CRITICAL ERROR initializing ADC: {e}", force=True)
        raise

    # LED
    try:
        _log(DMESG, "Initializing LED...", debug_mode=debug_mode)
        from hardware.led import RGBLED
        led_cfg = SYSCONFIG.get('LED')
        LED = RGBLED(
            DMESG=DMESG, REDLED=led_cfg['REDLED'], GREENLED=led_cfg['GREENLED'],
            BLUELED=led_cfg['BLUELED'], INVERT=led_cfg['INVERT'], ONCOLOR=led_cfg['ONCOLOR'],
            blink_timer_id=led_cfg['BLINK_TIMER']
        )
        LED.color("green")
        app_passthrough['LED'] = LED
    except Exception as e:
        _log(DMESG, f"CRITICAL ERROR initializing LED: {e}", force=True)
        raise

    # Drives
    try:
        _log(DMESG, "Initializing drives...", debug_mode=debug_mode)
        from hardware.drives import HBridge
        drv_cfg = SYSCONFIG.get('DRIVES')
        DRIVES = HBridge(
            DMESG=DMESG, peel1=drv_cfg['PEEL1_PIN'], peel2=drv_cfg['PEEL2_PIN'],
            drive1=drv_cfg['DRIVE1_PIN'], drive2=drv_cfg['DRIVE2_PIN'], enable=drv_cfg['ENABLE_PIN'],
            peelinvert=drv_cfg['PEEL_INVERT'], driveinvert=drv_cfg['DRIVE_INVERT'], enableinvert=drv_cfg['ENABLE_INVERT'],
            timer_id=drv_cfg['TIMER_ID'], pwm_frequency=drv_cfg['PWM_FREQUENCY'],
            peel1_ch=drv_cfg['PEEL1_CH'], peel2_ch=drv_cfg['PEEL2_CH'],
            drive1_ch=drv_cfg['DRIVE1_CH'], drive2_ch=drv_cfg['DRIVE2_CH'], autobrake=drv_cfg['AUTOBRAKE']
        )
        app_passthrough['DRIVES'] = DRIVES
    except Exception as e:
        _log(DMESG, f"CRITICAL ERROR initializing drives: {e}", force=True)
        raise

    # Encoder
    try:
        _log(DMESG, "Initializing encoder...", debug_mode=debug_mode)
        from hardware.encoder import Encoder
        enc_cfg = SYSCONFIG.get('ENCODER')
        ENCODER = Encoder(
            timer_num=enc_cfg['TIMER'], pin_a_name=enc_cfg['PINA'], pin_b_name=enc_cfg['PINB'],
            pin_af=enc_cfg['TIMER_AF'], ticks_per_revolution=enc_cfg['TPR'],
            max_count=enc_cfg.get('MAX', 65535), invert=enc_cfg.get('INVERT', False),
            DMESG=DMESG, LOG=debug_mode
        )
        app_passthrough['ENCODER'] = ENCODER
    except Exception as e:
        _log(DMESG, f"CRITICAL ERROR initializing encoder: {e}", force=True)
        raise

    # Servo
    try:
        _log(DMESG, "Initializing servo...", debug_mode=debug_mode)
        from system.servo import Servo
        servo_cfg = SYSCONFIG.get('SERVO')
        SERVO = Servo(
            drives=DRIVES, encoder=ENCODER, dmesg=DMESG,
            Kp=servo_cfg.get('P', 0.05), Ki=servo_cfg.get('I', 0.001), Kd=servo_cfg.get('D', 0.005),
            pid_taper=servo_cfg.get('PID_TAPER', 30), max_output=servo_cfg.get('MAX', 100), min_output=servo_cfg.get('MIN', 5),
            tolerance=servo_cfg.get('TOLERANCE', 5), backlash_takeup=servo_cfg.get('TAKEUP', 100),
            ramp_ticks=servo_cfg.get('RAMP_TICKS', 200), ramp_taper_percent=servo_cfg.get('RAMP_TAPER', 30),
            stable_updates=servo_cfg.get('UPDATES', 3), brake=servo_cfg.get('BRAKE', True),
            peel_enable=servo_cfg.get('PEEL_ENABLE', True), peel_speed=servo_cfg.get('PEEL_SPEED', 50),
            peel_time_ms=servo_cfg.get('PEEL_RUN_MS', 500), debug_enabled=servo_cfg.get('DEBUG', debug_mode)
        )
        app_passthrough['SERVO'] = SERVO
    except Exception as e:
        _log(DMESG, f"CRITICAL ERROR initializing servo: {e}", force=True)
        raise

    # RS485
    try:
        _log(DMESG, "Initializing RS485...", debug_mode=debug_mode)
        from hardware.rs485 import RS485
        rs485_cfg = SYSCONFIG.get('RS485')
        app_passthrough['RS485'] = RS485(
            slot_id=SYSCONFIG.get('SYSTEM.SLOTID', 0), de_pin_name=rs485_cfg['DE_PIN'],
            uart_id=rs485_cfg['UART_ID'], baudrate=rs485_cfg['BAUDRATE'], data_bits=rs485_cfg['DATA_BITS'],
            parity=rs485_cfg['PARITY'], stop_bits=rs485_cfg['STOP_BITS'], rx_buffer_size=rs485_cfg['BUFFER_SIZE'],
            DMESG=DMESG, LOG=debug_mode
        )
    except Exception as e:
        _log(DMESG, f"CRITICAL ERROR initializing RS485: {e}", force=True)
        raise

    _log(DMESG, "Hardware initialization complete.")

def run_bootstrap(app_passthrough: dict, LOG: bool = False):
    """Performs initial system setup."""
    DMESG, SYSCONFIG = app_passthrough.get('DMESG'), app_passthrough.get('SYSCONFIG')

    if not DMESG:
        print("BOOTSTRAP: CRITICAL ERROR - DMESG not found. Halting.")
        raise ValueError("DMESG instance required in app_passthrough.")

    if not SYSCONFIG:
        _log(DMESG, "CRITICAL ERROR - SYSCONFIG not found. Halting.", force=True)
        raise ValueError("SYSCONFIG instance required in app_passthrough.")

    debug_mode = SYSCONFIG.get('SYSTEM.DEBUG', False)

    _log(DMESG, "Starting...", debug_mode=debug_mode)

    _log_system_info(DMESG)
    _setup_identity(DMESG, SYSCONFIG, LOG, app_passthrough)
    _initialize_hardware(DMESG, SYSCONFIG, app_passthrough, LOG)

    gc.collect()
    _log(DMESG, "BOOTSTRAP: Initialization Complete.", force=True)