# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# misc.py - A place for misc things, the land of misfit toys, or where dreams come to die, you get it.

from os import statvfs
from machine import unique_id
from ubinascii import hexlify
import time
import asyncio

def _check_app_passthrough(app_passthrough):
    """Checks if required keys exist in app_passthrough."""
    if not isinstance(app_passthrough, dict):
        print("REPL Error: 'app_passthrough' is not a dictionary.")
        return False
    if 'DMESG' not in app_passthrough:
        print("REPL Error: 'DMESG' not found in 'app_passthrough'. Did main.py run successfully?")
        return False
    return True

def calibrate_test(app_passthrough):
    """Runs the calibration routine."""
    if not _check_app_passthrough(app_passthrough): 
        return

    dmesg = app_passthrough['DMESG']
    try:
        from util.calibrate import run_calibrate
        dmesg.log("REPL: Starting calibration...")
        run_calibrate(app_passthrough)
        dmesg.log("REPL: Calibration finished.")
    except ImportError:
        dmesg.log("REPL: Error - Could not import run_calibrate from util.calibrate.")
    except Exception as e:
        dmesg.log(f"REPL: Error during calibrate_test(): {e}")

def profiler_test(app_passthrough):
    """Runs the PID tuning profiler."""
    if not _check_app_passthrough(app_passthrough): 
        return

    dmesg = app_passthrough['DMESG']
    try:
        from util.profiler import run_performance_profiler
        dmesg.log("REPL: Starting profiler...")
        asyncio.run(run_performance_profiler(app_passthrough))
        dmesg.log("REPL: Profiler finished.")
    except ImportError:
        dmesg.log("REPL: Error - Could not import run_performance_profiler from util.profiler.")
    except Exception as e:
        dmesg.log(f"REPL: Error during profiler_test(): {e}")

def clicky_test(app_passthrough):
    """Runs the Clicky button test via util.clicky.run_test"""
    if not isinstance(app_passthrough, dict):
        print("REPL Error: Invalid app_passthrough provided.")
        return

    dmesg = app_passthrough.get('DMESG')

    try:
        from util.clicky import run_test
        if dmesg: 
            dmesg.log("REPL: Starting clicky button test...")
        print("Starting clicky button test...")

        asyncio.run(run_test(app_passthrough))

        if dmesg: 
            dmesg.log("REPL: Clicky button test finished or interrupted.")
        print("Clicky button test finished or interrupted.")

    except ImportError:
        err_msg = "REPL: Error - Could not import run_test from util.clicky."
        print(err_msg)
        if dmesg: 
            dmesg.log(err_msg)
    except KeyError as e:
        err_msg = f"REPL: Error - Missing key '{e}' in app_passthrough for clicky test."
        print(err_msg)
        if dmesg: 
            dmesg.log(err_msg)
    except KeyboardInterrupt:
        err_msg = "REPL: Clicky test interrupted by user at misc level."
        print(err_msg)
        if dmesg: 
            dmesg.log(err_msg)
    except Exception as e:
        err_msg = f"REPL: Error during clicky_test(): {e}"
        print(err_msg)
        if dmesg: 
            dmesg.log(err_msg)

def vfs_info(mount='/flash'):
    """Get filesystem info."""
    try:
        raw_vfs_info = statvfs(mount)
        block_size, _, num_blocks, free_blocks, _, *_ = raw_vfs_info
        size = round((num_blocks * block_size) / (1024 * 1024), 2)
        free = round((free_blocks * block_size) / (1024 * 1024), 2)
        return num_blocks, free_blocks, block_size, size, free
    except Exception as e:
        return None, e, None

def get_uuid():
    """Returns a 12-Byte Hex UUID based on the MCU's 96-bit Unique ID."""
    uid_bytes = unique_id()
    hex_uid = hexlify(uid_bytes).decode('utf-8')
    return (hex_uid + '0' * 24)[:24]  # Ensure 24 characters

def mem_usage():
    """Returns MCU total RAM, available RAM, used RAM, and free RAM."""
    try:
        import gc
        import micropython
        gc.collect()  # Force garbage collection for accurate reading
        
        # Get heap memory info
        heap_used = gc.mem_alloc()
        heap_free = gc.mem_free()
        heap_total = heap_used + heap_free
        
        # Try to get MCU total RAM from micropython.mem_info()
        mcu_total_ram = None
        try:
            import io
            import sys
            
            # Capture micropython.mem_info(1) output
            old_stdout = sys.stdout
            captured_output = io.StringIO()
            sys.stdout = captured_output
            
            micropython.mem_info(1)  # Get detailed memory info
            
            sys.stdout = old_stdout
            mem_info_output = captured_output.getvalue()
            
            # Parse the output - look for "GC: total: 88320" format
            for line in mem_info_output.split('\n'):
                if line.startswith('GC: total:'):
                    # Extract total from "GC: total: 88320, used: 49904, free: 38416"
                    parts = line.split(',')
                    total_part = parts[0]  # "GC: total: 88320"
                    mcu_total_ram = int(total_part.split(':')[2].strip())
                    break
        except Exception:
            pass
        
        # Fallback: try to determine from MCU type
        if mcu_total_ram is None:
            try:
                import os
                machine_info = os.uname().machine.upper()
                
                # Map known MCU types to RAM sizes
                if 'STM32F411' in machine_info:
                    mcu_total_ram = 128 * 1024  # 128KB
                elif 'STM32F405' in machine_info or 'STM32F407' in machine_info:
                    mcu_total_ram = 192 * 1024  # 192KB
                elif 'STM32F401' in machine_info:
                    mcu_total_ram = 96 * 1024   # 96KB
                elif 'STM32F429' in machine_info:
                    mcu_total_ram = 256 * 1024  # 256KB
                else:
                    # Final fallback: estimate based on heap + typical overhead
                    mcu_total_ram = heap_total + (40 * 1024)  # Assume 40KB system overhead
            except:
                mcu_total_ram = heap_total + (40 * 1024)
        
        # Calculate values:
        # Available RAM = heap total (what's available for programs)
        # Used RAM = heap used (how much of available RAM is used)
        # Free RAM = heap free (how much of available RAM is free)
        available_ram = heap_total  # This is what's available for programs
        used_ram = heap_used        # How much of available RAM is used
        free_ram = heap_free        # How much of available RAM is free
        
        # Cleanup and return
        return mcu_total_ram, available_ram, used_ram, free_ram
        
    except Exception as e:
        return None, None, None, None