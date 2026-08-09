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
import machine
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
    """Ctrl+C during boot launches the serial console - the single system menu.

    During normal operation the console is entered with ESC x3 (Ctrl+C is disabled
    there so the console owns the port); this handler only fires for an interrupt
    while bootstrap is running or has failed.
    """
    try:
        from system.console import SerialConsole
        # Boot context: restore Ctrl+C (kbd_intr 3) on exit so the REPL is usable.
        if asyncio.run(SerialConsole(app_passthrough, kbd_intr_resting=3).run()) == 'repl':
            print("Dropping to REPL...")
    except Exception as e:
        print(f"Console unavailable ({e}); dropping to REPL.")


### Run Bootstrap
try:
    run_bootstrap(app_passthrough)
except KeyboardInterrupt:
    handle_keyboard_interrupt()
except Exception as e:
    DMESG.log(f"MAIN: Bootstrap failed critically: {e}")
    # Attempt to signal failure via LED if it was initialized
    if 'LED' in app_passthrough:
        try:
            app_passthrough['LED'].state('fault')
        except Exception: pass

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


### Run the application. Import it (don't gate on os.path.exists, which only sees the
### filesystem, not frozen modules) so a frozen app.py launches in the appliance image;
### a /flash/app.py copy still shadows the frozen one for development overrides.
app_to_run = SYSCONFIG.get('SYSTEM.APP', 'app.py')
try:
    # Accept 'app.py' or a bare module name ('app') in SYSTEM.APP.
    app_module = __import__(app_to_run[:-3] if app_to_run.endswith('.py') else app_to_run)
    if hasattr(app_module, 'run_app'):
        app_module.run_app(app_passthrough)
    else:
        DMESG.log(f"ERROR: Application '{app_to_run}' has no 'run_app' function.")
        if 'LED' in app_passthrough: app_passthrough['LED'].state('fault')
except KeyboardInterrupt:
    handle_keyboard_interrupt()
except ImportError as e:
    DMESG.log(f"ERROR: Could not import application '{app_to_run}': {e}")
    if 'LED' in app_passthrough: app_passthrough['LED'].state('fault')
except Exception as e:
    DMESG.log(f"ERROR: Unhandled exception during application execution: {e}")
    if 'LED' in app_passthrough: app_passthrough['LED'].state('fault')
finally:
    DMESG.log("Application finished or failed.")

