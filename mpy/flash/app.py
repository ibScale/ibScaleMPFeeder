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

def log_interval(app_globals, perf_stats=None):
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
    
    # Add performance stats if provided
    if perf_stats:
        servo_avg, servo_min, servo_max, servo_std = perf_stats['servo']
        photon_avg, photon_min, photon_max, photon_std = perf_stats['photon']
        tick_avg, tick_min, tick_max, tick_std = perf_stats['tick']
        
        log_message += (f" Perf(ms): Servo {servo_avg}±{servo_std} ({servo_min}-{servo_max}), "
                       f"Photon {photon_avg}±{photon_std} ({photon_min}-{photon_max}), "
                       f"Tick {tick_avg}±{tick_std} ({tick_min}-{tick_max});")

    return log_message

@micropython.viper
def calc_stats_viper(times_list):
    """Viper compiled stats calculation for maximum speed"""
    n = int(len(times_list))
    if n == 0:
        return (0, 0, 0, 0)
    if n == 1:
        val = int(times_list[0])
        return (val, val, val, 0)
    
    # Calculate basic stats
    total = 0
    min_val = int(times_list[0])
    max_val = int(times_list[0])
    
    for i in range(n):
        val = int(times_list[i])
        total += val
        if val < min_val:
            min_val = val
        if val > max_val:
            max_val = val
    
    avg = total // n
    
    # Calculate standard deviation
    variance_sum = 0
    for i in range(n):
        diff = int(times_list[i]) - avg
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
        servo_stats = calc_stats_viper(servo_data)
        photon_stats = calc_stats_viper(photon_data)
        tick_stats = calc_stats_viper(tick_data)
        sleep_stats = calc_stats_viper(sleep_data)
        
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
    
    # Photon protocol support
    try:
        from photon import Photon
        node_address = SYSCONFIG.get('SYSTEM.SLOTID', 0)
        uuid = SYSCONFIG.get('SYSTEM.UUID', 0)
        PHOTON = Photon(NETWORK, DMESG, SERVO, LED, node_address=node_address, uuid=uuid)
        log_msg(f"Photon initialized - Node: {node_address}, UUID: {uuid}")
    except Exception as e:
        log_msg(f"Failed to initialize Photon: {e}")
        LED.color('red')
        return
    
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
                
                # Run Servo first for consistent time intervals
                SERVO.update()
                servo_stop = time.ticks_ms()
                
                # Run Photon state machine
                PHOTON.update()
                photon_stop = time.ticks_ms()
                
                # Provide heartbeat and maintenance
                loop_count += 1
                if loop_count >= log_time_count:
                    loop_count = 0
                    gc_count += 1
                    if gc_count >= gc_time_count:
                        gc_count = 0
                        gc.collect()
                    
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

                if gc_count != 0:
                    log_msg(f"Loop overrun: {loop_elapsed}ms (target: {loop_time_ms}ms)")
                
            except Exception as e:
                log_msg(f"Main loop error: {e}")
                await asyncio.sleep_ms(100)
    
    # Run the loop
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
        log_msg("Application cleanup")
