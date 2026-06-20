# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# app.py - Application wrapper, I.E. launching point for photon or modbus or whatever
# This also calls the servo and other classes responsible for running the hardware

import asyncio
import time
import gc
import micropython
from util.misc import mem_usage, vfs_info
from system.watchdog import start as wdt_start, feed as wdt_feed

def log_interval(app_globals):
    """
    Generates the interval log message and does some basic maintenance
    """
    mcu_total, available, used, free = mem_usage()
    log_message = f"TICK - Memory: {used}/{available} ({round(used/available*100)}%);"
    blocks, free_blocks, block_size, size_mb, free_mb = vfs_info('/flash')

    used_blocks, used_mb = blocks - free_blocks, size_mb - free_mb
    log_message += f" VFS: {used_blocks}/{blocks}blks ({round(used_blocks/blocks*100)}%);"

    VDC = app_globals['ADC'].vmonvdc()
    VSYS = app_globals['ADC'].vmonsys()
    temp = app_globals['ADC'].temp()
    log_message += f" VDC: {VDC}, VSYS: {VSYS}, Temp: {temp};"

    return log_message

def calc_stats(times_list):
    """Calculate (avg, min, max, std_dev) for a list of timing samples."""
    n = len(times_list)
    if n == 0:
        return (0, 0, 0, 0)
    if n == 1:
        val = times_list[0]
        return (val, val, val, 0)

    # Calculate basic stats
    total = 0
    min_val = max_val = times_list[0]

    for val in times_list:
        total += val
        if val < min_val:
            min_val = val
        if val > max_val:
            max_val = val

    avg = total // n

    # Calculate standard deviation
    variance_sum = 0
    for val in times_list:
        diff = val - avg
        variance_sum += diff * diff

    variance = variance_sum // n
    
    # Integer square root
    std_dev = 0
    if variance > 0:
        x = variance
        while True:
            y = (x + variance // x) // 2
            if y >= x:
                std_dev = x
                break
            x = y
    
    return (avg, min_val, max_val, std_dev)


def format_perf_stats(perf_stats):
    """Format performance statistics"""
    servo_avg, servo_min, servo_max, servo_std = perf_stats['servo']
    photon_avg, photon_min, photon_max, photon_std = perf_stats['photon']
    tick_avg, tick_min, tick_max, tick_std = perf_stats['tick']
    sleep_avg, sleep_min, sleep_max, sleep_std = perf_stats['sleep']
    
    return (f"Servo {servo_avg}±{servo_std} ({servo_min}-{servo_max}), "
            f"Photon {photon_avg}±{photon_std} ({photon_min}-{photon_max}), "
            f"Tick {tick_avg}±{tick_std} ({tick_min}-{tick_max}), "
            f"Sleep {sleep_avg}±{sleep_std} ({sleep_min}-{sleep_max})")

async def calculate_and_log_stats(servo_data, photon_data, tick_data, sleep_data, log_msg):
    """Background task to calculate and log performance stats"""
    try:
        # Calculate stats using viper function
        servo_stats = calc_stats(servo_data)
        photon_stats = calc_stats(photon_data)
        tick_stats = calc_stats(tick_data)
        sleep_stats = calc_stats(sleep_data)
        
        # Package stats
        perf_stats = {
            'servo': servo_stats,
            'photon': photon_stats,
            'tick': tick_stats,
            'sleep': sleep_stats
        }
        
        # Log performance message
        log_msg(f"Performance - {format_perf_stats(perf_stats)}")
        
    except Exception as e:
        log_msg(f"Stats calculation error: {e}")



### Main entry point here
def run_app(app_globals):
    """
    Main application wrapper called by main.py.
    """
    DMESG = app_globals['DMESG']
    SYSCONFIG = app_globals['SYSCONFIG']
    LED = app_globals['LED']
    SERVO = app_globals['SERVO']
    NETWORK = app_globals['RS485']
    BTNUP = app_globals.get('BTNUP')
    BTNDOWN = app_globals.get('BTNDOWN')
    ENCODER = app_globals.get('ENCODER')

    # Manual jog distances derived from encoder scaling (TICKS_010MM = ticks per 0.1mm)
    ticks_per_mm = SYSCONFIG.get('SYSTEM.TICKS_010MM', 22.546) * 10
    jog_click_ticks = max(1, int(ticks_per_mm))         # ~1mm per short click
    jog_hold_ticks = max(1, int(ticks_per_mm * 200))    # far target; a held button feeds until released
    # Speed profile for this feeder slot's parts (gentle/normal/fast); the future
    # Photon feed path should read the same key.
    slot_profile = SYSCONFIG.get('SYSTEM.SLOT_PROFILE', 'normal')

    # Main loop settings
    loop_time_ms = SYSCONFIG.get('APP.LOOP_INTERVAL_MS', 20) # Main control loop (20ms)
    tick_time_ms = SYSCONFIG.get('APP.TICK_INTERVAL_MS', 5000) # Heartbeat interval (5secs)
    gc_time_ms = SYSCONFIG.get('APP.GC_INTERVAL_MS', 60000) # Garbage collection interval (1min)
    log_time_count = int(tick_time_ms // loop_time_ms)
    gc_time_count = int(gc_time_ms // tick_time_ms)
    
    # Simple logging function
    def log_msg(message):
        DMESG.log(f"APP: {message}")
    
    log_msg("Application starting...")
    LED.color('green')
    
    # Photon protocol support (optional - manual jog via buttons still works without it)
    PHOTON = None
    try:
        from application.photon import Photon
        node_address = SYSCONFIG.get('SYSTEM.SLOTID', 0)
        uuid = SYSCONFIG.get('SYSTEM.UUID', 0)
        PHOTON = Photon(NETWORK, DMESG, SERVO, LED, SYSCONFIG,
                        eeprom=app_globals.get('EEPROM'), node_address=node_address, uuid=uuid)
        log_msg(f"Photon initialized - Node: {node_address}, UUID: {uuid}")
    except Exception as e:
        log_msg(f"Photon unavailable ({e}) - running in manual mode (buttons only)")

    # Serial console over USB VCP (press ESC three times to enter an interactive menu)
    try:
        from system.console import SerialConsole
        CONSOLE = SerialConsole(app_globals)
        log_msg("Serial console ready - press ESC three times to enter")
    except Exception as e:
        log_msg(f"Console unavailable: {e}")
        CONSOLE = None

    # Manual jog handler for the UP/DOWN buttons.
    # Short click: jog a fixed step. Hold (long press): feed continuously until released.
    def service_buttons():
        for btn, direction, name in ((BTNUP, 1, 'fwd'), (BTNDOWN, -1, 'rev')):
            if not btn:
                continue
            btn.poll()
            evt = btn.get_event()
            if evt == 'click':
                # Grid-indexed jog: feed() targets the absolute commanded grid, so the
                # previous move's residual is auto-corrected (no cumulative drift). Run it
                # as a real-time burst (run_move) for an accurate, jitter-free stop.
                target = SERVO.feed(direction * jog_click_ticks, profile=slot_profile)
                SERVO.run_move()
                log_msg(f"Button: jog {name} {jog_click_ticks}t -> {target} ({SERVO.result_name})")
            elif evt == 'long_press':
                # Free-hand sweep from the actual position; deliberately not grid-indexed.
                target = SERVO.get_current_position() + direction * jog_hold_ticks
                SERVO.set_target(target, profile=slot_profile)
                log_msg(f"Button: hold {name} start")
            elif evt == 'release':
                SERVO.stop()
                # Re-anchor the grid to wherever the free-hand sweep actually ended.
                SERVO.reseed()
                log_msg(f"Button: hold {name} stop")
            elif evt == 'double_click':
                # Zero the position reference. Stop first so the servo doesn't chase a
                # setpoint that just shifted, then reset the encoder and the commanded
                # grid together so the two references stay in sync.
                SERVO.stop()
                if ENCODER:
                    ENCODER.reset()
                SERVO.reseed()
                log_msg("Button: position zeroed")

    # Where the magic happens
    async def main_loop():
        loop_count = 0
        gc_count = 0
        
        # Rolling statistics for performance monitoring
        servo_times = []
        photon_times = []
        tick_times = []
        sleep_times = []
        max_samples = 100
        calculate_stats = False
        
        while True:
            try:
                # Record start time
                loop_start = time.ticks_ms()
                wdt_feed()  # keep the watchdog happy each control cycle

                # Serial console: ESC x3 enters an interactive menu. The app is paused
                # (servo stopped) while the menu is open; resume cleanly afterwards.
                if CONSOLE and CONSOLE.poll():
                    SERVO.stop()
                    LED.color('cyan')
                    result = await CONSOLE.run()
                    LED.color('green')
                    if result == 'repl':
                        log_msg("Exiting to REPL from console")
                        SERVO.disable()
                        return
                    SERVO.reseed()  # re-anchor the grid; the motor may have moved
                    continue

                # Service manual jog buttons (may issue a new SERVO target)
                service_buttons()

                # Run Servo first for consistent time intervals
                SERVO.update()
                servo_stop = time.ticks_ms()

                # Run Photon state machine
                if PHOTON:
                    PHOTON.update()
                photon_stop = time.ticks_ms()
                
                # Provide heartbeat and maintenance
                ran_gc = False
                loop_count += 1
                if loop_count >= log_time_count:
                    loop_count = 0
                    gc_count += 1
                    if gc_count >= gc_time_count:
                        gc_count = 0
                        gc.collect()
                        ran_gc = True

                    # Log basic message
                    log_msg(log_interval(app_globals))
                    
                    # Set flag to calculate stats in background
                    calculate_stats = True
                    
                tick_stop = time.ticks_ms()

                # Calculate timing for this loop
                servo_elapsed = time.ticks_diff(servo_stop, loop_start)
                photon_elapsed = time.ticks_diff(photon_stop, servo_stop)
                tick_elapsed = time.ticks_diff(tick_stop, photon_stop)
                
                # Calculate sleep time to maintain loop timing
                loop_elapsed = time.ticks_diff(time.ticks_ms(), loop_start)
                sleep_time = max(0, loop_time_ms - loop_elapsed)
                
                # Add to rolling statistics
                servo_times.append(servo_elapsed)
                if len(servo_times) > max_samples:
                    servo_times.pop(0)
                    
                photon_times.append(photon_elapsed)
                if len(photon_times) > max_samples:
                    photon_times.pop(0)
                    
                tick_times.append(tick_elapsed)
                if len(tick_times) > max_samples:
                    tick_times.pop(0)
                
                sleep_times.append(sleep_time)
                if len(sleep_times) > max_samples:
                    sleep_times.pop(0)
            
                # Start stats calculation task if needed (non-blocking)
                if calculate_stats:
                    calculate_stats = False
                    asyncio.create_task(calculate_and_log_stats(servo_times[:], photon_times[:], tick_times[:], sleep_times[:], log_msg))
                
                if sleep_time > 0:
                    await asyncio.sleep_ms(sleep_time)
                    continue

                if not ran_gc:
                    log_msg(f"Loop overrun: {loop_elapsed}ms (target: {loop_time_ms}ms)")
                
            except Exception as e:
                log_msg(f"Main loop error: {e}")
                await asyncio.sleep_ms(100)
    
    # Optional hardware watchdog (off unless SYSTEM.WATCHDOG_S is set). Once armed it
    # runs until reset and is fed from every blocking loop (here, run_move, the console,
    # and the dev tools).
    wdt_s = SYSCONFIG.get('SYSTEM.WATCHDOG_S', 0)
    if wdt_start(int(wdt_s * 1000)):   # config is seconds; machine.WDT wants ms
        log_msg(f"Watchdog armed ({wdt_s}s)")

    # Run the loop. Disable Ctrl+C so the serial console fully owns the VCP and ESC x3
    # is the single way in; restored on exit so the REPL gets Ctrl+C back.
    micropython.kbd_intr(-1)
    try:
        log_msg("Starting main loop")
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        log_msg("Application interrupted by user")
        LED.color('yellow')
        raise
    except Exception as e:
        log_msg(f"Application error: {e}")
        LED.color('red')
    finally:
        micropython.kbd_intr(3)
        log_msg("Application cleanup")
