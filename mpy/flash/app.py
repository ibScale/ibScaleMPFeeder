# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# app.py - Application wrapper, I.E. launching point for photon or modbus or whatever
# This also calls the servo and other classes responsible for running the hardware

import asyncio
import time
import micropython
from util.misc import mem_usage, vfs_info
from system.watchdog import start as wdt_start, feed as wdt_feed
from system.gcutil import collect as gc_collect, ran_recently as gc_ran_recently
from system.servo import RESULT_STALLED, RESULT_TIMEOUT

def log_interval(vdc, vsys, temp):
    """Generate the heartbeat log message. The ADC values are passed in - read once
    per tick by the main loop and shared with the fault checks there. Every source
    can fail (all-None tuples / None readings); the heartbeat must degrade to 'n/a'
    rather than crash, or it would mask the underlying problem with a loop error."""
    mcu_total, available, used, free = mem_usage()
    if available:
        log_message = f"TICK - Memory: {used}/{available} ({round(used/available*100)}%);"
    else:
        log_message = "TICK - Memory: n/a;"

    blocks, free_blocks, block_size, size_mb, free_mb = vfs_info('/flash')
    if blocks:
        used_blocks = blocks - free_blocks
        log_message += f" VFS: {used_blocks}/{blocks}blks ({round(used_blocks/blocks*100)}%);"
    else:
        log_message += " VFS: n/a;"

    log_message += f" VDC: {vdc}, VSYS: {vsys}, Temp: {temp};"

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
    
    return (f"Servo {servo_avg}±{servo_std} ({servo_min}-{servo_max}), " +
            f"Photon {photon_avg}±{photon_std} ({photon_min}-{photon_max}), " +
            f"Tick {tick_avg}±{tick_std} ({tick_min}-{tick_max}), " +
            f"Sleep {sleep_avg}±{sleep_std} ({sleep_min}-{sleep_max})")

async def calculate_and_log_stats(servo_data, photon_data, tick_data, sleep_data, log_msg):
    """Background task to calculate and log performance stats"""
    try:
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
    ADC = app_globals.get('ADC')
    BTNUP = app_globals.get('BTNUP')
    BTNDOWN = app_globals.get('BTNDOWN')
    ENCODER = app_globals.get('ENCODER')

    # Overtemperature threshold for the LED fault indicator (0 disables the check).
    temp_max_c = SYSCONFIG.get('SYSTEM.TEMP_MAX_C', 70)

    # Voltage-range thresholds for the LED fault indicator (rail out of spec = fault).
    vdc_min = SYSCONFIG.get('ADC.VDC_MIN', 20.0)
    vdc_max = SYSCONFIG.get('ADC.VDC_MAX', 28.0)
    vsys_min = SYSCONFIG.get('ADC.VSYS_MIN', 9.0)
    vsys_max = SYSCONFIG.get('ADC.VSYS_MAX', 11.0)

    # Manual jog distances derived from encoder scaling (TICKS_010MM = ticks per 0.1mm)
    ticks_per_mm = SYSCONFIG.get('SYSTEM.TICKS_010MM', 22.546) * 10
    jog_mm = SYSCONFIG.get('APP.JOG_MM', 2)
    jog_click_ticks = max(1, int(ticks_per_mm * jog_mm))  # JOG_MM mm per short click
    jog_hold_ticks = max(1, int(ticks_per_mm * 200))    # far target; a held button feeds until released
    slot_profile = SYSCONFIG.get('APP.SLOT_PROFILE', 'normal')

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

    # Photon protocol support (optional - manual jog via buttons still works without it).
    # Photon.__init__ takes over LED status duty from the boot default (purple) as soon
    # as it's constructed, setting yellow until CMD_INITIALIZE_FEEDER succeeds (green).
    PHOTON = None
    try:
        from application.photon import Photon
        node_address = SYSCONFIG.get('SYSTEM.SLOT_ID', 255)
        uuid = SYSCONFIG.get('SYSTEM.UUID', 0)
        PHOTON = Photon(NETWORK, DMESG, SERVO, LED, SYSCONFIG,
                        eeprom=app_globals.get('EEPROM'), node_address=node_address, uuid=uuid)
        log_msg(f"Photon initialized - Node: {node_address}, UUID: {uuid}")
    except Exception as e:
        log_msg(f"Photon unavailable ({e}) - running in manual mode (buttons only)")
        LED.state('ready')  # no Photon lifecycle to drive the LED - just show ready

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
                # The peel motor is started/stopped by Servo itself (tracking the actual
                # drive move), so it keeps running for the whole hold and is cut on release.
                # timeout_ms=0: the hold is bounded by the button release (and stall
                # detection), not the per-move time cap - a >10s hold must keep feeding.
                target = SERVO.get_current_position() + direction * jog_hold_ticks
                SERVO.set_target(target, profile=slot_profile, timeout_ms=0)
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
        overtemp_active = False
        voltage_fault_active = False
        led_fault_active = False
        led_prefault_color = None   # color() to restore once the fault clears
        
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

                # Advance any active LED blink (non-blocking, event-loop driven)
                LED.poll()

                # Serial console: ESC x3 enters an interactive menu. The app is paused
                # (servo stopped) while the menu is open; blink the current color for the
                # duration as the "console is open" indicator (console.py itself calls
                # LED.poll() during its input-wait loop to keep the blink animating).
                # blink() only toggles on/off over whatever color() last set - it doesn't
                # change or need to save/restore the color itself, so this is safe to use
                # even if a fault is turning the LED red at the same time.
                if CONSOLE and CONSOLE.poll():
                    SERVO.stop()
                    LED.blink()
                    result = await CONSOLE.run()
                    LED.blink(0)
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
                loop_count += 1
                if loop_count >= log_time_count:
                    loop_count = 0
                    gc_count += 1
                    if gc_count >= gc_time_count:
                        gc_count = 0
                        gc_collect()

                    # Read the ADC once per tick; the heartbeat message and the
                    # fault checks below share these values.
                    vdc = ADC.vmonvdc() if ADC else None
                    vsys = ADC.vmonsys() if ADC else None
                    mcu_temp = ADC.temp() if ADC else None

                    # Log basic message
                    log_msg(log_interval(vdc, vsys, mcu_temp))

                    # Set flag to calculate stats in background
                    calculate_stats = True

                    # Overtemperature check - thermal drift is slow, so heartbeat
                    # cadence (APP.TICK_INTERVAL_MS) is frequent enough.
                    if temp_max_c > 0 and mcu_temp is not None:
                        new_overtemp = mcu_temp >= temp_max_c
                        if new_overtemp != overtemp_active:
                            # Conditional pulled out of the f-string: MicroPython's
                            # lexer treats the ':' inside the quoted text as the
                            # start of a format spec (SyntaxError when frozen).
                            state = 'FAULT: Over temperature' if new_overtemp else 'Temperature back to normal'
                            log_msg(f"{state} ({mcu_temp:.0f}C, limit {temp_max_c}C)")
                        overtemp_active = new_overtemp

                    # Voltage-range check - same slow-drift reasoning as overtemp;
                    # heartbeat cadence is frequent enough to catch a bad rail.
                    vdc_bad = vdc is not None and not (vdc_min <= vdc <= vdc_max)
                    vsys_bad = vsys is not None and not (vsys_min <= vsys <= vsys_max)
                    new_voltage_fault = vdc_bad or vsys_bad
                    if new_voltage_fault != voltage_fault_active:
                        if new_voltage_fault:
                            log_msg(f"FAULT: Voltage out of range (VDC={vdc}V [{vdc_min}-{vdc_max}], " +
                                    f"VSYS={vsys}V [{vsys_min}-{vsys_max}])")
                        else:
                            log_msg(f"Voltage back to normal (VDC={vdc}V, VSYS={vsys}V)")
                    voltage_fault_active = new_voltage_fault

                tick_stop = time.ticks_ms()

                # LED fault indicator: solid red for as long as any fault condition
                # holds (motor stall/timeout from any source - Photon move, button
                # click/hold-jog - overtemperature, or an out-of-range supply rail).
                # On the rising edge, remember whatever color() was showing so it can be
                # restored once the fault clears; color('red') is reasserted every tick
                # while already active so it always wins over any color set earlier this
                # tick (e.g. Photon's cyan-restore or CMD_INITIALIZE_FEEDER's green).
                fault_now = overtemp_active or voltage_fault_active or SERVO.result in (RESULT_STALLED, RESULT_TIMEOUT)
                if fault_now:
                    if not led_fault_active:
                        led_prefault_color = LED.current_color
                    LED.state('fault')
                    led_fault_active = True
                elif led_fault_active:
                    led_fault_active = False
                    LED.color(led_prefault_color)

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

                # A GC pass alone can take longer than the loop budget - that's a known,
                # already-accounted-for cost (APP.GC_INTERVAL_MS), not a real scheduling
                # problem, so don't log it as an overrun. gc_ran_recently() catches this
                # loop's own gc_collect() above AND any collect() triggered elsewhere
                # during this same iteration (e.g. sysconfig.save() from a Photon
                # PROGRAM_FEEDER_FLOOR command) that this loop has no other way to see.
                if not gc_ran_recently(loop_time_ms):
                    log_msg(f"Loop overrun: {loop_elapsed}ms (target: {loop_time_ms}ms)")

                # Overrun path: still yield once so queued tasks (the stats
                # calculation) and any other coroutines get CPU time even under
                # sustained overrun - otherwise create_task()'d work piles up unrun.
                await asyncio.sleep_ms(0)

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
        LED.state('stopped')
        raise
    except Exception as e:
        log_msg(f"Application error: {e}")
        LED.state('fault')
    finally:
        micropython.kbd_intr(3)
        log_msg("Application cleanup")
