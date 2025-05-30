# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# clicky.py - Test buttons for single-press, double-press, and long-press

import time
import asyncio

async def run_test(app_passthrough):
    """
    Tests the UP and DOWN buttons by polling Button objects found in app_passthrough.
    Detects single clicks, double clicks, and long presses.

    Args:
        app_passthrough (dict): Dictionary containing initialized objects from main.py.
                                Expected keys: 'BTNUP', 'BTNDOWN', 'DMESG'.
    """
    # --- Get Objects ---
    DMESG = app_passthrough.get('DMESG')
    BTNUP = app_passthrough.get('BTNUP')
    BTNDOWN = app_passthrough.get('BTNDOWN')

    # --- Check required objects ---
    if not all([BTNUP, BTNDOWN]):
        err_msg = "CLICKY: ERROR - Missing required Button objects ('BTNUP', 'BTNDOWN') in app_passthrough."
        if DMESG:
            DMESG.log(err_msg)
        else:
            print(err_msg)
        return # Cannot proceed without buttons

    # --- Start Test ---
    if DMESG:
        DMESG.log("CLICKY: Starting Button Test...")
    print("\n--- Button Test ---")
    print("Test the UP (BTNUP) and DOWN (BTNDOWN) buttons:")
    print("- Single Click")
    print("- Double Click")
    print("- Long Press (check button config for timing)")
    print("- Release after Long Press (if latched)")
    print("Press Ctrl+C in the REPL to stop the test.")
    print("--------------------")

    last_print_time = time.ticks_ms()
    print_interval_ms = 5000
    active = True
    stopped_by_user = False

    while active:
        try:
            # Poll buttons using the extracted objects
            BTNUP.poll()
            BTNDOWN.poll()

            # Check for events
            btn_up_event = BTNUP.get_event()
            if btn_up_event:
                print(f"UP Button Event: {btn_up_event}")
                if DMESG: DMESG.log(f"UP Button Event: {btn_up_event}")

            btn_down_event = BTNDOWN.get_event()
            if btn_down_event:
                print(f"DOWN Button Event: {btn_down_event}")
                if DMESG: DMESG.log(f"DOWN Button Event: {btn_down_event}")

            now = time.ticks_ms()
            if time.ticks_diff(now, last_print_time) > print_interval_ms:
                 print(f"Status: UP={BTNUP.is_pressed()}, DOWN={BTNDOWN.is_pressed()}")
                 last_print_time = now

            # Let other tasks run and control polling rate
            await asyncio.sleep_ms(20)

        except KeyboardInterrupt:
            print("\nButton test stopped by user.")
            if DMESG: DMESG.log("CLICKY: Button test stopped by user.")
            stopped_by_user = Trueg
            break

        except Exception as e:
            err_msg = f"CLICKY: Error during button test loop: {e}"
            print(err_msg)
            if DMESG: DMESG.log(err_msg)
            active = False

    if not stopped_by_user:
        print("--- Button Test Finished ---")
        if DMESG: DMESG.log("CLICKY: Button Test Finished.")