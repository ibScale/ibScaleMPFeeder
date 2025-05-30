# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# test.py - Calibration test for the drives and encoder

import time
import sys
import select
import math

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

    # --- Get Objects from Passthrough ---
    DRIVES = app_passthrough.get('DRIVES')
    ENCODER = app_passthrough.get('ENCODER')
    DMESG = app_passthrough.get('DMESG')
    SYSCONFIG = app_passthrough.get('SYSCONFIG')
    LED = app_passthrough.get('LED')

    # --- Safety Checks ---
    if not all([DRIVES, ENCODER, DMESG, SYSCONFIG]): # Check for SYSCONFIG too
        print("ERROR: Missing required objects (DRIVES, ENCODER, DMESG, SYSCONFIG) in app_passthrough!")
        return # Cannot proceed

    # Keep log for specific messages if needed, but use print for user interaction
    log = DMESG.log

    # --- Helper for Confirmation/Input ---
    def get_input(prompt_message, timeout_s):
        # Use print for user-facing prompt
        print(f"{prompt_message} (Y/N - {timeout_s}s timeout): ", end='')
        poller = select.poll()
        poller.register(sys.stdin, select.POLLIN)
        res = poller.poll(timeout_s * 1000)
        if res:
            user_input = sys.stdin.readline().strip().upper()
            print(user_input) # Echo input
            return user_input
        else:
            print("Timeout")
            return None

    # --- Ask for Test Confirmations ---
    print("--- Calibration Selection ---")
    encoder_confirm = get_input(f"Run DRIVE PWM Minimum Calibration test?", CONFIRM_TIMEOUT_S)
    run_encoder_calib_test = encoder_confirm == 'Y'

    peel_confirm = get_input(f"Run PEEL motor direction test ({PEEL_SPEED_PERCENT}%)?", CONFIRM_TIMEOUT_S)
    run_peel_test = peel_confirm == 'Y'

    led_confirm = get_input(f"Run RGB LED test?", CONFIRM_TIMEOUT_S)
    run_led_test = led_confirm == 'Y'

    # Update exit condition
    if not run_encoder_calib_test and not run_peel_test and not run_led_test:
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
            initial_start_count = ENCODER.count
            time.sleep_ms(INITIAL_SPIN_DURATION_MS)
            ENCODER.update()
            initial_end_count = ENCODER.count

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
                    print(f"Setting absolute PWM: {current_pwm}%")
                    DRIVES.drive_set(current_pwm, absolute_pwm=True)
                    time.sleep_ms(50) # Allow PWM to settle briefly
                    ENCODER.update()
                    start_count = ENCODER.count
                    time.sleep_ms(CALIBRATION_INTERVAL_MS)
                    ENCODER.update()
                    end_count = ENCODER.count

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
                        print(f"Setting absolute PWM: {current_pwm}%")
                        DRIVES.drive_set(current_pwm, absolute_pwm=True)
                        time.sleep_ms(50) # Allow PWM to settle briefly
                        ENCODER.update()
                        start_count = ENCODER.count
                        time.sleep_ms(CALIBRATION_INTERVAL_MS)
                        ENCODER.update()
                        end_count = ENCODER.count

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

            print("Commanding motor to stop (PWM 0%). Measuring coasting ticks...")
            ENCODER.update()
            encoder_at_stop_command = ENCODER.count
            DRIVES.drive_set(0, absolute_pwm=True)

            consecutive_no_movement_intervals = 0
            last_encoder_count_coasting = encoder_at_stop_command
            encoder_at_actual_stop = encoder_at_stop_command

            max_coasting_checks = 20
            checks_done = 0

            while consecutive_no_movement_intervals < COAST_TEST_STOP_CHECK_INTERVALS and checks_done < max_coasting_checks:
                time.sleep_ms(CALIBRATION_INTERVAL_MS)
                ENCODER.update()
                current_encoder_count_coasting = ENCODER.count
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

            # Round up to the nearest 100
            rounded_coasting_ticks = math.ceil(coasting_ticks / 100.0) * 100
            print(f"Rounded coasting ticks (SERVO.RAMP): {int(rounded_coasting_ticks)}")

            # Save to SYSCONFIG as SERVO.RAMP
            SYSCONFIG.set('SERVO.RAMP', int(rounded_coasting_ticks))
            config_changed = True 

            log(f"CALIBRATE: Drive coasting ticks: {coasting_ticks}, SERVO.RAMP set to: {int(rounded_coasting_ticks)}")
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

        # --- Run LED Test ---
        if run_led_test:
            print(f"--- Starting RGB LED Test ---")
            if hasattr(LED, 'test'):
                try:
                    LED.test()
                    print("LED test sequence complete.")
                except Exception as led_e:
                    print(f"ERROR during LED test: {led_e}")
            else:
                print("ERROR: LED object does not have a 'test' method.")
            print("--- LED Test Finished ---")


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
            log(f"CALIBRATE: Results - Drive/Encoder/Peel Invert: {SYSCONFIG.get('DRIVES.DRIVE_INVERT', False)}/{SYSCONFIG.get('ENCODER.INVERT', False)}/{SYSCONFIG.get('DRIVES.PEEL_INVERT', False)}, Drive PWM Min: {SYSCONFIG.get('DRIVES.DRIVE_PWM_MIN')}, Servo Ramp: {SYSCONFIG.get('SERVO.RAMP')}")

            if config_changed:
                print("Saving updated SYSCONFIG...")
                SYSCONFIG.save()
                print("SYSCONFIG saved.")

        except Exception as final_stop_e:
             print(f"Error during final cleanup: {final_stop_e}")

        print("--- Calibration Script Finished ---")