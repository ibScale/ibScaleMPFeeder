# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>
#
# main.py - Gluon firmware (Photon gives you light, Gluon gives you color)
#
# Gluon is a re-implementation of the Photon feeder software used in the LumenPNP.
# It's designed to run on the ibScaleMPFeeder motherboard that is physically
# compatible with the stock LumenPNP Feeder body and Photon protocol.

import asyncio
import os
import os.path
import machine
import pyb
from system.dmesg import DmesgLogger
import gc
from system.sysconfig import SysConfig
from system.bootstrap import run_bootstrap
import time
from util.misc import mem_usage

### DMESG and SYSCONFIG need to be setup first since everything depends on them
DMESG = DmesgLogger(file_logging_enabled=False)
DMESG.log("Gluon firmware Starting...")
app_passthrough = {'DMESG': DMESG}
SYSCONFIG = SysConfig(DMESG=DMESG, LOG=False)
app_passthrough['SYSCONFIG'] = SYSCONFIG


### Some shortcuts for the REPL and keyboard interrupt handler
def dfu(): # Enter DFU Bootloader
    machine.bootloader()
def calibrate():
    from util.misc import calibrate_test
    calibrate_test(app_passthrough)
def profiler():
    from util.misc import profiler_test
    profiler_test(app_passthrough)
def clicky():
    from util.misc import clicky_test
    clicky_test(app_passthrough)

def handle_keyboard_interrupt():
    """Handle Ctrl+C interrupt with user choice"""
    print("\n\nKeyboard interrupt detected!")
    print("Options:")
    print("1. Drop to REPL")
    print("2. Reboot application")
    print("3. Reset Hardware")
    print("4. Enter DFU mode")
    print("5. Calibration")
    print("6. PID Profiler")
    print("7. Button test")
    
    while True:
        try:
            choice = input("Enter choice (1/2/3/4/5/6/7): ").strip()
            if choice == '1':
                print("Dropping to REPL...")
                return
            elif choice == '2':
                print("Rebooting application...")
                machine.soft_reset()
                return
            elif choice == '3':
                print("Reseting hardware...")
                machine.reset()
                return
            elif choice == '4':
                print("Entering DFU mode...")
                machine.bootloader()
                return
            elif choice == '5':
                print("Running calibration...")
                calibrate()
                return
            elif choice == '6':
                print("Running PID profiler...")
                profiler()
                return
            elif choice == '7':
                print("Running button test...")
                clicky()
                return
            else:
                print("Invalid choice. Please try again.")
        except Exception:
            print("Invalid input. Please try again.")


### Run Bootstrap
try:
    run_bootstrap(app_passthrough, LOG=False)
except KeyboardInterrupt:
    handle_keyboard_interrupt()
except Exception as e:
    DMESG.log(f"MAIN: Bootstrap failed critically: {e}")
    # Attempt to signal failure via LED if it was initialized
    if 'LED' in app_passthrough:
        try:
            app_passthrough['LED'].color('yellow')
            app_passthrough['LED'].blink('red')
        except: pass
    
    # Give user immediate options
    print(f"\nBOOTSTRAP FAILED: {e}")
    print("Press Ctrl+C for recovery options, or system will halt...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        handle_keyboard_interrupt()

# Memory info
mcu_total, available, used, free = mem_usage()
if mcu_total:
    system_reserved = mcu_total - available
    DMESG.log(f"RAM: MCU={mcu_total}B, System={system_reserved}B, Available={available}B, Used={used}B ({used/available*100:.1f}%), Free={free}B")
else:
    DMESG.log("RAM: Could not read memory info")

gc.collect()
DMESG.log(f"GLUON: Starting application...")


### Run the application
app_to_run = SYSCONFIG.get('SYSTEM.APP', 'app.py')
if os.path.exists(app_to_run):
    try:
        # Dynamically import and run the main function of the application module
        app_module = __import__(app_to_run[:-3])
        if hasattr(app_module, 'run_app'):
            # Call the application's run_app function directly.
            app_module.run_app(app_passthrough)
        else:
             DMESG.log(f"ERROR: Application '{app_to_run}' exists but does not have a 'run_app' function.")
             if 'LED' in app_passthrough: app_passthrough['LED'].blink('red')

    except KeyboardInterrupt:
        handle_keyboard_interrupt()
    except ImportError:
        DMESG.log(f"ERROR: Could not import application module '{app_to_run}' even though it exists.")
        if 'LED' in app_passthrough: app_passthrough['LED'].blink('red')
    except Exception as e:
        DMESG.log(f"ERROR: Unhandled exception during application execution: {e}")
        if 'LED' in app_passthrough: app_passthrough['LED'].blink('red')
    finally:
        DMESG.log("Application finished or failed.")

else:
    DMESG.log(f"ERROR: Application file '{app_to_run}' not found.")
    if 'LED' in app_passthrough: app_passthrough['LED'].blink('red')

