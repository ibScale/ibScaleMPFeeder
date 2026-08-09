# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# test.py - Calibration test for the drives and encoder

import time
import sys
import select
import math
from system.watchdog import feed as wdt_feed

def run_calibrate(app_passthrough):
    """
    Calibrates the drive motors and encoder. Motors will turn on during this test.

    Args:
        app_passthrough (dict): Dictionary containing initialized objects from main.py.
                                Expected keys: 'DRIVES', 'ENCODER', 'DMESG', 'SYSCONFIG'.
    """
    # --- Configuration ---
    CONFIRM_TIMEOUT_S = 5 # How long to wait for confirmation
    DIRECTION_TIMEOUT_S = 15 # How long to wait for direction confirmation
    CALIBRATION_INTERVAL_MS = 500 # How often to adjust PWM and check encoder
    INITIAL_SPIN_DURATION_MS = 1000 # How long to spin initially
    PWM_STEP = 5 # Step to adjust absolute PWM during calibration
    PEEL_SPEED_PERCENT = 75 # Peel motor test speed
    COAST_TEST_FULL_SPEED_DURATION_MS = 2000 # Run at full speed for 2s before coast test
    COAST_TEST_STOP_CHECK_INTERVALS = 3 # Number of CALIBRATION_INTERVAL_MS to confirm stop
    BUTTON_GESTURE_TIMEOUT_S = 10 # How long to wait for each requested button gesture

    # --- Get Objects from Passthrough ---
    DRIVES = app_passthrough.get('DRIVES')
    ENCODER = app_passthrough.get('ENCODER')
    DMESG = app_passthrough.get('DMESG')
    SYSCONFIG = app_passthrough.get('SYSCONFIG')
    LED = app_passthrough.get('LED')
    BTNUP = app_passthrough.get('BTNUP')
    BTNDOWN = app_passthrough.get('BTNDOWN')

    # --- Safety Checks ---
    if not all([DRIVES, ENCODER, DMESG, SYSCONFIG]): # Check for SYSCONFIG too
        print("ERROR: Missing required objects (DRIVES, ENCODER, DMESG, SYSCONFIG) in app_passthrough!")
        return # Cannot proceed

    # Keep log for specific messages if needed, but use print for user interaction
    log = DMESG.log

    # --- Helper for Confirmation/Input ---
    def get_input(prompt_message, timeout_s, hint='Y/N'):
        # Use print for user-facing prompt
        print(f"{prompt_message} ({hint} - {timeout_s}s timeout): ", end='')
        poller = select.poll()
        poller.register(sys.stdin, select.POLLIN)
        # Poll in short chunks so the watchdog (if armed) gets fed during a long wait.
        deadline = time.ticks_add(time.ticks_ms(), timeout_s * 1000)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            wdt_feed()
            if poller.poll(200):
                user_input = sys.stdin.readline().strip().upper()
                print(user_input) # Echo input
                return user_input
        print("Timeout")
        return None

    def wait_for_button_event(btn, expected, timeout_s):
        """Poll `btn` until it reports the `expected` event ('click'/'double_click'/
        'long_press'), ignoring any other event that lands while waiting. Returns
        False after timeout_s with no match."""
        while btn.get_event() is not None:
            pass  # drain anything stale queued from before this gesture was asked for
        deadline = time.ticks_add(time.ticks_ms(), timeout_s * 1000)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            wdt_feed()
            btn.poll()
            evt = btn.get_event()
            while evt is not None:            # drain every event queued this tick
                if evt == expected:
                    return True
                evt = btn.get_event()
            time.sleep_ms(20)
        return False

    # --- Ask for Test Confirmations ---
    print("--- Calibration Selection ---")
    encoder_confirm = get_input(f"Run DRIVE PWM Minimum Calibration test?", CONFIRM_TIMEOUT_S)
    run_encoder_calib_test = encoder_confirm == 'Y'

    peel_confirm = get_input(f"Run PEEL motor direction test ({PEEL_SPEED_PERCENT}%)?", CONFIRM_TIMEOUT_S)
    run_peel_test = peel_confirm == 'Y'

    button_confirm = get_input("Run button test (guided click/double-click/long-press)?", CONFIRM_TIMEOUT_S)
    run_button_test = button_confirm == 'Y'

    led_confirm = get_input("Calibrate the LED (polarity + channel colors)?", CONFIRM_TIMEOUT_S)
    run_led_calib = led_confirm == 'Y'

    # Update exit condition
    if not run_encoder_calib_test and not run_peel_test and not run_button_test and not run_led_calib:
        print("No tests selected. Exiting calibration script.")
        print("--- Calibration Script Finished ---")
        return

    # --- Main Test Execution ---
    print("--- Starting Selected Tests ---")
    config_changed = False
    try:
        # --- Enable Drives (only if needed for motor tests) ---
        if run_encoder_calib_test or run_peel_test:
            print("Enabling drives...")
            DRIVES.enable(True)
            time.sleep_ms(100)

        # --- Run Drive PWM Minimum Calibration Test ---
        if run_encoder_calib_test:
            print(f"--- Starting Drive PWM Minimum Calibration ---")
            print(f"Interval: {CALIBRATION_INTERVAL_MS}ms, PWM Step: {PWM_STEP}")

            # 1. Initial Spin & Movement Check
            print(f"Initial spin at 100% for {INITIAL_SPIN_DURATION_MS}ms...")
            DRIVES.drive_set(100, absolute_pwm=True)
            ENCODER.update()
            initial_start_count = ENCODER.absolute_count
            time.sleep_ms(INITIAL_SPIN_DURATION_MS)
            ENCODER.update()
            initial_end_count = ENCODER.absolute_count

            if initial_start_count == initial_end_count:
                print("ERROR: Encoder count did not change during initial spin. Motor not moving or encoder issue.")
                print("Stopping drive motor.")
                DRIVES.drive_set(0, absolute_pwm=True)
            else:
                print("Initial movement confirmed.")
                current_pwm = 100
                last_moving_pwm = 100
                pwm_at_stop = -1

                # 2. Reduce PWM until movement stops
                print("Reducing PWM until encoder movement stops...")
                while current_pwm >= 0:
                    wdt_feed()
                    print(f"Setting absolute PWM: {current_pwm}%")
                    DRIVES.drive_set(current_pwm, absolute_pwm=True)
                    time.sleep_ms(50) # Allow PWM to settle briefly
                    ENCODER.update()
                    start_count = ENCODER.absolute_count
                    time.sleep_ms(CALIBRATION_INTERVAL_MS)
                    ENCODER.update()
                    end_count = ENCODER.absolute_count

                    if start_count == end_count:
                        print(f"Movement stopped at or below {current_pwm}% PWM.")
                        pwm_at_stop = current_pwm
                        break
                    else:
                        last_moving_pwm = current_pwm

                    current_pwm -= PWM_STEP
                    if current_pwm < 0:
                         print("PWM reached 0, movement did not stop?")
                         pwm_at_stop = 0
                         break

                # 3. Increase PWM until movement starts again
                found_min_pwm = -1
                if pwm_at_stop != -1:
                    print("Increasing PWM until encoder movement restarts...")
                    current_pwm = pwm_at_stop
                    while current_pwm <= 100:
                        wdt_feed()
                        print(f"Setting absolute PWM: {current_pwm}%")
                        DRIVES.drive_set(current_pwm, absolute_pwm=True)
                        time.sleep_ms(50) # Allow PWM to settle briefly
                        ENCODER.update()
                        start_count = ENCODER.absolute_count
                        time.sleep_ms(CALIBRATION_INTERVAL_MS)
                        ENCODER.update()
                        end_count = ENCODER.absolute_count

                        if start_count != end_count:
                            print(f"Movement restarted at {current_pwm}% PWM.")
                            found_min_pwm = current_pwm
                            break
                        else:
                             pass

                        current_pwm += PWM_STEP
                        if current_pwm > 100:
                            print("PWM reached 100, movement did not restart?")
                            break
                else:
                    print("Skipping PWM increase step as movement never stopped.")


                # 4. Store the result
                if found_min_pwm != -1:
                    print(f"Found minimum drive PWM for movement: {found_min_pwm}%")
                    SYSCONFIG.set('DRIVES.DRIVE_PWM_MIN', found_min_pwm)
                    config_changed = True
                else:
                    print("Could not determine minimum PWM value.")

                # 5. Check Drive/Encoder Direction (after calibration)
                print("Performing direction check...")
                DRIVES.drive_set(50, absolute_pwm=False)
                time.sleep_ms(CALIBRATION_INTERVAL_MS * 2)
                ENCODER.update()
                encoder_direction_reading = ENCODER.direction
                print(f"Encoder direction reading: {encoder_direction_reading}")

                direction_confirm = get_input("Is the DRIVE motor spinning FORWARD?", DIRECTION_TIMEOUT_S)

                if direction_confirm == 'Y':
                    print("User confirms physical direction is FORWARD.")
                    if SYSCONFIG.get('DRIVES.DRIVE_INVERT', False):
                        print("Setting DRIVES.DRIVE_INVERT to False.")
                        SYSCONFIG.set('DRIVES.DRIVE_INVERT', False)
                        config_changed = True

                    # Now check encoder reading relative to FORWARD physical motion
                    # Compare against integer values
                    if encoder_direction_reading == -1: # Encoder reads REVERSE (-1)
                        print("Encoder reads REVERSE (-1) (incorrect). Setting ENCODER.INVERT to True.")
                        if not SYSCONFIG.get('ENCODER.INVERT', False):
                            SYSCONFIG.set('ENCODER.INVERT', True)
                            config_changed = True
                    elif encoder_direction_reading == 1: # Encoder reads FORWARD (1)
                        print("Encoder reads FORWARD (1) (correct). Ensuring ENCODER.INVERT is False.")
                        if SYSCONFIG.get('ENCODER.INVERT', False):
                            SYSCONFIG.set('ENCODER.INVERT', False)
                            config_changed = True
                    else: # Encoder stopped (0) or indeterminate
                        print(f"Encoder direction '{encoder_direction_reading}' (0=Stopped) indeterminate during forward check.")

                elif direction_confirm == 'N': # Physical motion is REVERSE
                    print("User reports physical direction is REVERSE.")
                     # Ensure DRIVE_INVERT is True
                    if not SYSCONFIG.get('DRIVES.DRIVE_INVERT', False):
                        print("Setting DRIVES.DRIVE_INVERT to True.")
                        SYSCONFIG.set('DRIVES.DRIVE_INVERT', True)
                        config_changed = True

                    # Now check encoder reading relative to REVERSE physical motion
                    if encoder_direction_reading == 1:
                        print("Encoder reads FORWARD (1) (incorrect for reverse motion). Setting ENCODER.INVERT to True.")
                        if not SYSCONFIG.get('ENCODER.INVERT', False):
                            SYSCONFIG.set('ENCODER.INVERT', True)
                            config_changed = True
                    elif encoder_direction_reading == -1:
                        print("Encoder reads REVERSE (-1) (correct for reverse motion). Ensuring ENCODER.INVERT is False.")
                        if SYSCONFIG.get('ENCODER.INVERT', False):
                            SYSCONFIG.set('ENCODER.INVERT', False)
                            config_changed = True
                    else: # Encoder stopped (0) or indeterminate
                        print(f"Encoder direction '{encoder_direction_reading}' (0=Stopped) indeterminate during reverse check.")

                else:
                     print("No valid direction confirmation received for DRIVE motor.")

                print("Stopping drive motor...")
                DRIVES.drive_set(0)
                time.sleep_ms(100)

            print("--- Drive PWM Calibration Finished ---")

            # --- Measure Coasting Distance from Full Speed ---
            print(f"--- Starting Drive Coasting Distance Measurement ---")
            print(f"Running motor at 100% for {COAST_TEST_FULL_SPEED_DURATION_MS}ms...")
            DRIVES.drive_set(100, absolute_pwm=True, brake=False)
            time.sleep_ms(COAST_TEST_FULL_SPEED_DURATION_MS)

            print("Commanding motor to coast (PWM 0%, no brake). Measuring coasting ticks...")
            ENCODER.update()
            encoder_at_stop_command = ENCODER.absolute_count
            # Coast (brake=False) so we measure the natural runway; the servo's
            # auto_brake default would otherwise brake and skew the measurement.
            DRIVES.drive_set(0, absolute_pwm=True, brake=False)

            consecutive_no_movement_intervals = 0
            last_encoder_count_coasting = encoder_at_stop_command
            encoder_at_actual_stop = encoder_at_stop_command

            max_coasting_checks = 20
            checks_done = 0

            while consecutive_no_movement_intervals < COAST_TEST_STOP_CHECK_INTERVALS and checks_done < max_coasting_checks:
                wdt_feed()
                time.sleep_ms(CALIBRATION_INTERVAL_MS)
                ENCODER.update()
                current_encoder_count_coasting = ENCODER.absolute_count
                print(f"Coasting check: Current count {current_encoder_count_coasting}, Last count {last_encoder_count_coasting}")

                if current_encoder_count_coasting == last_encoder_count_coasting:
                    consecutive_no_movement_intervals += 1
                else:
                    consecutive_no_movement_intervals = 0
                
                last_encoder_count_coasting = current_encoder_count_coasting
                encoder_at_actual_stop = current_encoder_count_coasting
                checks_done +=1

            if checks_done >= max_coasting_checks:
                print("Warning: Coasting check loop reached max iterations. Result might be inaccurate.")

            coasting_ticks = abs(encoder_at_actual_stop - encoder_at_stop_command)
            print(f"Encoder at stop command: {encoder_at_stop_command}")
            print(f"Encoder at actual stop: {encoder_at_actual_stop}")
            print(f"Motor coasted for approximately {coasting_ticks} ticks from full speed.")

            # The coasting distance from full speed is the natural deceleration runway,
            # so it seeds the profile's MAX->CREEP ramp (DECEL_TICKS). Half of it seeds
            # the slow creep tail (CREEP_TICKS) as a starting point; the servo auto-tuner
            # (option 6 / profiler) then refines CREEP speed and the creep tail.
            rounded_coasting_ticks = int(math.ceil(coasting_ticks / 100.0) * 100)
            decel_ticks = max(100, rounded_coasting_ticks)
            creep_ticks = max(100, int(math.ceil((rounded_coasting_ticks / 2.0) / 50.0) * 50))
            print(f"Coasted ~{coasting_ticks} ticks -> SERVO.DECEL_TICKS={decel_ticks}, SERVO.CREEP_TICKS={creep_ticks}")

            SYSCONFIG.set('SERVO.DECEL_TICKS', decel_ticks)
            SYSCONFIG.set('SERVO.CREEP_TICKS', creep_ticks)
            config_changed = True

            log(f"CALIBRATE: Drive coasting ticks: {coasting_ticks}, SERVO.DECEL_TICKS={decel_ticks}, SERVO.CREEP_TICKS={creep_ticks}")
            print(f"--- Drive Coasting Distance Measurement Finished ---")


        # --- Run Peel Test ---
        if run_peel_test:
            print(f"--- Starting Peel Motor Test ({PEEL_SPEED_PERCENT}%) ---")
            print(f"Setting peel speed to {PEEL_SPEED_PERCENT}%...")
            DRIVES.peel_set(PEEL_SPEED_PERCENT)

            # Immediately ask for direction confirmation
            print(f"Peel motor running at {PEEL_SPEED_PERCENT}%...")
            direction_confirm = get_input("Is the PEEL motor spinning FORWARD?", DIRECTION_TIMEOUT_S)

            # Stop the motor after getting input or timeout
            print("Stopping peel motor...")
            DRIVES.peel_set(0)
            time.sleep_ms(100)

            # Process the confirmation result
            if direction_confirm == 'N':
                print("Incorrect PEEL direction reported. Setting PEEL_INVERT flag to True in SYSCONFIG.")
                if not SYSCONFIG.get('DRIVES.PEEL_INVERT', False):
                    SYSCONFIG.set('DRIVES.PEEL_INVERT', True)
                    config_changed = True
            elif direction_confirm == 'Y':
                 print("Correct PEEL direction confirmed.")
                 if SYSCONFIG.get('DRIVES.PEEL_INVERT', False):
                     print("Setting DRIVES.PEEL_INVERT to False.")
                     SYSCONFIG.set('DRIVES.PEEL_INVERT', False)
                     config_changed = True
            else:
                 print("No valid direction confirmation received for PEEL motor.")

            print("--- Peel Motor Test Finished ---")

        # --- Run Button Test (guided click / double-click / long-press) ---
        if run_button_test:
            print(f"--- Starting Button Test ---")
            if not all([BTNUP, BTNDOWN]):
                print("ERROR: Missing required Button objects (BTNUP, BTNDOWN) in app_passthrough.")
            else:
                gestures = (('single click', 'click'), ('double click', 'double_click'), ('long press', 'long_press'))
                for name, btn in (('UP', BTNUP), ('DOWN', BTNDOWN)):
                    for label, expected in gestures:
                        print(f"Press the {name} button: {label} ({BUTTON_GESTURE_TIMEOUT_S}s timeout)...")
                        ok = wait_for_button_event(btn, expected, BUTTON_GESTURE_TIMEOUT_S)
                        result = "OK" if ok else "TIMEOUT - no matching event detected"
                        print(f"  {name} {label}: {result}")
                        log(f"CALIBRATE: Button {name} {label}: {result}")
            print("--- Button Test Finished ---")

        # --- Run LED Calibration (polarity + which channel lights which color) ---
        if run_led_calib:
            print(f"--- Starting LED Calibration ---")
            if not hasattr(LED, 'probe'):
                print("ERROR: LED object does not support wiring calibration (no 'probe' method).")
            else:
                try:
                    COLOR_NAMES = {'R': 'RED', 'G': 'GREEN', 'B': 'BLUE'}

                    def ask_color(prompt, choices):
                        hint = '/'.join(COLOR_NAMES[c] for c in choices)
                        ans = get_input(prompt, DIRECTION_TIMEOUT_S, hint=hint)
                        if ans:
                            for c in choices:
                                if ans == c or ans == COLOR_NAMES[c]:
                                    return c
                        return None

                    # 1. Polarity: drive raw PWM 0 on every channel and ask if the LED is off.
                    #    If it's still lit, 0 duty means "on" electrically (common anode),
                    #    so INVERT must be True to make 0 mean off.
                    LED.set_invert(False)
                    LED.probe(None)
                    off_confirm = get_input("LED driven to raw-zero on all channels - is it OFF?", CONFIRM_TIMEOUT_S)
                    found_invert = (off_confirm == 'N')
                    LED.set_invert(found_invert)
                    LED.probe(None)  # re-assert off using the now-correct polarity
                    print(f"LED polarity: {'Common Cathode (INVERT=True)' if found_invert else 'Common Anode (INVERT=False)'}")

                    # 2. Identify which physical channel (RED_CH pin, then GREEN_CH pin) lights
                    #    which color. The third (BLUE_CH pin) is deduced - whatever's left.
                    remaining = ['R', 'G', 'B']
                    channel_map = [None, None, None]
                    aborted = False
                    for idx in (0, 1):
                        LED.probe(idx)
                        color = ask_color(f"Channel {idx} is lit - is it RED, GREEN, or BLUE?", remaining)
                        if color is None:
                            print(f"No valid color reported for channel {idx}; aborting wiring calibration.")
                            aborted = True
                            break
                        channel_map[idx] = color
                        remaining.remove(color)

                    if aborted:
                        LED.probe(None)
                    else:
                        channel_map[2] = remaining[0]
                        LED.probe(2)
                        print(f"Channel 2 is lit - deduced as {COLOR_NAMES[channel_map[2]]} (the only color left).")
                        LED.set_channel_map(channel_map)

                        print(f"LED channel map (0=RED_CH pin, 1=GREEN_CH pin, 2=BLUE_CH pin): {channel_map}")
                        SYSCONFIG.set('LED.INVERT', found_invert)
                        SYSCONFIG.set('LED.CHANNEL_COLORS', channel_map)
                        config_changed = True

                        print("LED wiring calibration complete - cycling through colors (500ms/color) to confirm...")
                        LED.test(delay_ms=500)
                except Exception as wiring_e:
                    print(f"ERROR during LED calibration: {wiring_e}")
            print("--- LED Calibration Finished ---")


    except Exception as e:
        print(f"ERROR during test execution: {e}")
        try:
            # Only stop drives if they might have been running
            if run_encoder_calib_test or run_peel_test:
                DRIVES.drive_set(0)
                DRIVES.peel_set(0)
                DRIVES.enable(False)
        except Exception as stop_e:
            print(f"Error stopping drives after exception: {stop_e}")

    finally:
        # --- Final Cleanup ---
        print("--- Final Test Cleanup ---")
        try:
            if run_encoder_calib_test or run_peel_test:
                print("Ensuring motors are stopped...")
                DRIVES.drive_set(0)
                DRIVES.peel_set(0)
                time.sleep_ms(100)
                # Disable drives if they were enabled
                if DRIVES.enabled:
                     print("Disabling drives...")
                     DRIVES.enable(False)
                else:
                     print("Drives already disabled.")

            # Give feedback
            log(f"CALIBRATE: Results - Drive/Encoder/Peel Invert: {SYSCONFIG.get('DRIVES.DRIVE_INVERT', False)}/{SYSCONFIG.get('ENCODER.INVERT', False)}/{SYSCONFIG.get('DRIVES.PEEL_INVERT', False)}, Drive PWM Min: {SYSCONFIG.get('DRIVES.DRIVE_PWM_MIN')}, Servo Decel/Creep ticks: {SYSCONFIG.get('SERVO.DECEL_TICKS')}/{SYSCONFIG.get('SERVO.CREEP_TICKS')}, LED Invert/ChannelColors: {SYSCONFIG.get('LED.INVERT')}/{SYSCONFIG.get('LED.CHANNEL_COLORS')}")

            if config_changed:
                print("Saving updated SYSCONFIG...")
                SYSCONFIG.save()
                print("SYSCONFIG saved.")

        except Exception as final_stop_e:
             print(f"Error during final cleanup: {final_stop_e}")

        print("--- Calibration Script Finished ---")