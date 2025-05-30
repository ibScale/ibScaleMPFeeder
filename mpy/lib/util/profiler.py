# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# profiler.py - Utility to help tune the PID loop and test the software servo
# Likely want to run this whenever you change parts/reels/tape/etc

# Dear PID gods, me again. Feel free to re-implement this one too :)

import asyncio
import time
import sys
from micropython import const

# --- Constants ---
_LOOP_INTERVAL_MS = const(20)
_MOVE_TIMEOUT_S = 8
_DEFAULT_MOVES = [900, 450, -900]
_NUM_TEST_RUNS = 5
_PAUSE_BETWEEN_MOVES_MS = const(200)
_PAUSE_BETWEEN_RUNS_MS = const(500)
_DEFAULT_KP = 0.05
_DEFAULT_KI = 0.005
_DEFAULT_KD = 0.001

# Module-level persistent profile settings
_PROFILE_RUNS = 10
_PROFILE_TICKS = 900

def _calculate_median(sorted_list):
    n = len(sorted_list)
    if n == 0:
        return float('nan')
    mid_idx = n // 2
    if n % 2 == 1:
        return sorted_list[mid_idx]
    else:
        return (sorted_list[mid_idx - 1] + sorted_list[mid_idx]) / 2.0

def _log(message, dmesg=None, prefix="PID_PROFILER:"):
    full_message = f"{prefix} {message}"
    if dmesg and hasattr(dmesg, 'log'):
        dmesg.log(full_message)
    else:
        print(full_message)

async def _execute_single_move(servo, encoder, dmesg, relative_move, log_prefix=""):
    """Executes a single relative move and collects performance metrics."""
    encoder.update()
    start_pos_initial = encoder.absolute_count
    target_pos = start_pos_initial + relative_move
    _log(f"{log_prefix}Requesting move from {start_pos_initial} to {target_pos} (Rel: {relative_move})", dmesg)
    start_time_ms = time.ticks_ms()
    max_abs_deviation_from_target = 0
    servo.set_target(target_pos)
    move_active = True

    while move_active:
        move_active = servo.update()
        encoder.update()
        current_pos = encoder.absolute_count
        current_deviation = abs(current_pos - target_pos)
        max_abs_deviation_from_target = max(max_abs_deviation_from_target, current_deviation)
        if not move_active:
            break
        if time.ticks_diff(time.ticks_ms(), start_time_ms) > (_MOVE_TIMEOUT_S * 1000):
            _log(f"{log_prefix}Move to {target_pos} TIMED OUT after {_MOVE_TIMEOUT_S}s.", dmesg)
            encoder.update()
            final_pos_on_timeout = encoder.absolute_count
            return {
                "relative_move": relative_move,
                "target": target_pos,
                "settling_time_s": _MOVE_TIMEOUT_S,
                "final_position": final_pos_on_timeout,
                "final_error": final_pos_on_timeout - target_pos,
                "max_abs_deviation_from_target": max_abs_deviation_from_target,
                "directional_overshoot": 0,
                "timeout": True
            }
        await asyncio.sleep_ms(_LOOP_INTERVAL_MS)

    end_time_ms = time.ticks_ms()
    settling_time_s = time.ticks_diff(end_time_ms, start_time_ms) / 1000.0
    encoder.update()
    final_position = encoder.absolute_count
    final_error = final_position - target_pos
    directional_overshoot = 0
    if relative_move > 0 and final_position > target_pos:
        directional_overshoot = final_position - target_pos
    elif relative_move < 0 and final_position < target_pos:
        directional_overshoot = target_pos - final_position

    _log(f"{log_prefix}Move to {target_pos} completed. Time: {settling_time_s:.3f}s, FinalPos: {final_position}, Err: {final_error}, DirOvershoot: {directional_overshoot}", dmesg)
    return {
        "relative_move": relative_move,
        "target": target_pos,
        "settling_time_s": settling_time_s,
        "final_position": final_position,
        "final_error": final_error,
        "max_abs_deviation_from_target": max_abs_deviation_from_target,
        "directional_overshoot": directional_overshoot,
        "timeout": False
    }

async def _run_test_sequence_for_one_iteration(servo, encoder, dmesg, moves, log_prefix=""):
    """Runs a sequence of moves once."""
    sequence_results = []
    _log(f"{log_prefix}Starting test sequence: {moves}", dmesg)
    encoder.reset()
    await asyncio.sleep_ms(50)
    encoder.update()
    _log(f"{log_prefix}Encoder reset. Initial count: {encoder.absolute_count}", dmesg)

    for move_idx, rel_move in enumerate(moves):
        move_log_prefix = f"{log_prefix}Move {move_idx+1}/{len(moves)} "
        move_metrics = await _execute_single_move(servo, encoder, dmesg, rel_move, log_prefix=move_log_prefix)
        move_metrics["move_index_in_sequence"] = move_idx
        sequence_results.append(move_metrics)
        if move_metrics["timeout"]:
            _log(f"{log_prefix}A move timed out. Aborting current test sequence iteration.", dmesg)
            break
        await asyncio.sleep_ms(_PAUSE_BETWEEN_MOVES_MS)

    if not servo.is_target_reached:
        _log(f"{log_prefix}Ensuring servo is stopped after sequence iteration (servo reports not at target).", dmesg)
        servo.stop()
    return sequence_results

def _summarize_run_results(run_results_list, run_number, dmesg):
    """Calculates and logs summary for one full run of the sequence."""
    if not run_results_list:
        _log(f"Run {run_number}: No results to summarize.", dmesg)
        return None

    completed_moves_data = [r for r in run_results_list if not r["timeout"]]
    num_moves_total = len(run_results_list)
    num_moves_completed = len(completed_moves_data)
    num_timeouts = num_moves_total - num_moves_completed

    avg_settling_time = float('nan')
    avg_abs_final_error = float('nan')
    max_directional_overshoot_in_run = 0

    if num_moves_completed > 0:
        total_settling_time = sum(r["settling_time_s"] for r in completed_moves_data)
        total_abs_final_error = sum(abs(r["final_error"]) for r in completed_moves_data)
        max_directional_overshoot_in_run = max(r["directional_overshoot"] for r in completed_moves_data) if completed_moves_data else 0
        
        avg_settling_time = total_settling_time / num_moves_completed
        avg_abs_final_error = total_abs_final_error / num_moves_completed

    summary = {
        "run_number": run_number,
        "avg_settling_time_s": avg_settling_time,
        "avg_abs_final_error": avg_abs_final_error,
        "max_directional_overshoot_in_run": max_directional_overshoot_in_run,
        "moves_completed": num_moves_completed,
        "moves_timed_out": num_timeouts,
        "total_moves_in_sequence": num_moves_total,
        "individual_moves_data": run_results_list 
    }

    _log(f"--- Summary for Run {run_number} ---", dmesg)
    _log(f"  Moves: {num_moves_completed}/{num_moves_total} completed.", dmesg)
    if num_timeouts > 0:
        _log(f"  Timeouts: {num_timeouts}", dmesg)
    if num_moves_completed > 0:
        _log(f"  Avg Settling Time (completed moves): {avg_settling_time:.3f}s", dmesg)
        _log(f"  Avg Abs Final Error (completed moves): {avg_abs_final_error:.2f} ticks", dmesg)
        _log(f"  Max Directional Overshoot (completed moves): {max_directional_overshoot_in_run:.2f} ticks", dmesg)
    _log("--------------------------", dmesg)
    return summary

def _calculate_and_log_average_per_move_type(all_individual_moves_data, default_moves_sequence, dmesg):
    """Calculates and logs the average performance for each type of move."""
    if not all_individual_moves_data:
        _log("No individual move data to calculate per-move-type average.", dmesg)
        return

    aggregated_data_by_move_type = {}
    for i in range(len(default_moves_sequence)):
        aggregated_data_by_move_type[i] = {
            "description": default_moves_sequence[i],
            "settling_times_completed": [],
            "abs_final_errors_completed": [],
            "directional_overshoots_completed": [],
            "count_completed": 0,
            "count_timeout": 0,
            "num_attempted": 0
        }

    for move_result in all_individual_moves_data:
        move_idx_in_seq = move_result.get("move_index_in_sequence")
        if move_idx_in_seq is None or move_idx_in_seq not in aggregated_data_by_move_type:
            _log(f"Warning: Move result found without valid 'move_index_in_sequence': {move_result}", dmesg)
            continue
        
        aggregator = aggregated_data_by_move_type[move_idx_in_seq]
        aggregator["num_attempted"] += 1

        if move_result.get("timeout", False):
            aggregator["count_timeout"] += 1
        else:
            aggregator["count_completed"] += 1
            aggregator["settling_times_completed"].append(move_result.get("settling_time_s", 0.0))
            aggregator["abs_final_errors_completed"].append(abs(move_result.get("final_error", 0)))
            aggregator["directional_overshoots_completed"].append(move_result.get("directional_overshoot", 0))

    _log("--- Performance Summary by Move Type (Across All Runs) ---", dmesg)
    for move_idx, data in aggregated_data_by_move_type.items():
        _log(f"  Move Type: {data['description']:+d} ticks (Index {move_idx})", dmesg)
        _log(f"    Attempts: {data['num_attempted']}, Completed: {data['count_completed']}, Timeouts: {data['count_timeout']}", dmesg)

        if data["count_completed"] > 0:
            st_list = data["settling_times_completed"]
            avg_st = sum(st_list) / data["count_completed"]
            st_sorted = sorted(st_list)
            min_st = st_sorted[0]
            max_st = st_sorted[-1]
            median_st = _calculate_median(st_sorted)
            _log(f"    Settling Time (s): Avg={avg_st:.3f}, Min={min_st:.3f}, Max={max_st:.3f}, Median={median_st:.3f}", dmesg)

            afe_list = data["abs_final_errors_completed"]
            avg_afe = sum(afe_list) / data["count_completed"]
            afe_sorted = sorted(afe_list)
            min_afe = afe_sorted[0]
            max_afe = afe_sorted[-1]
            median_afe = _calculate_median(afe_sorted)
            _log(f"    Abs Final Error (ticks): Avg={avg_afe:.2f}, Min={min_afe:.2f}, Max={max_afe:.2f}, Median={median_afe:.2f}", dmesg)

            do_list = data["directional_overshoots_completed"]
            avg_do = sum(do_list) / data["count_completed"]
            do_sorted = sorted(do_list)
            min_do = do_sorted[0]
            max_do = do_sorted[-1]
            median_do = _calculate_median(do_sorted)
            _log(f"    Dir. Overshoot (ticks): Avg={avg_do:.2f}, Min={min_do:.2f}, Max={max_do:.2f}, Median={median_do:.2f}", dmesg)

        elif data["num_attempted"] > 0 :
             _log("    No moves of this type completed successfully.", dmesg)
        _log("  -----------------------------------------------------------------", dmesg)

def get_pid_values_from_user(current_kp, current_ki, current_kd, dmesg):
    """Gets new PID values from the user via blocking input."""
    _log("Enter new PID values. Press Enter to keep current value.", dmesg)
    try:
        inp_kp_str = input(f"  Kp (current: {current_kp:.4f}): ").strip()
        new_kp = float(inp_kp_str) if inp_kp_str else current_kp
        
        inp_ki_str = input(f"  Ki (current: {current_ki:.4f}): ").strip()
        new_ki = float(inp_ki_str) if inp_ki_str else current_ki
        
        inp_kd_str = input(f"  Kd (current: {current_kd:.4f}): ").strip()
        new_kd = float(inp_kd_str) if inp_kd_str else current_kd
        
        _log(f"Using PID: Kp={new_kp:.4f}, Ki={new_ki:.4f}, Kd={new_kd:.4f}", dmesg)
        return new_kp, new_ki, new_kd
    except ValueError:
        _log("Invalid input. Using previous PID values.", dmesg)
        return current_kp, current_ki, current_kd

def suggest_pid_from_results(current_kp, current_ki, current_kd, move_summaries, target_error=5, target_overshoot=5):
    """Suggest new PID values based on average error and overshoot heuristics."""
    avg_error = sum(m['avg_abs_final_error'] for m in move_summaries) / len(move_summaries)
    avg_overshoot = sum(m['avg_directional_overshoot'] for m in move_summaries) / len(move_summaries)
    kp, ki, kd = current_kp, current_ki, current_kd
    error_factor = min(max(avg_error / target_error, 1), 3)
    overshoot_factor = min(max(avg_overshoot / target_overshoot, 1), 3)

    if avg_error > target_error and avg_overshoot > target_overshoot:
        kp *= 1 + 0.05 * error_factor
        ki *= 1 + 0.05 * error_factor
        kd *= 1 + 0.10 * overshoot_factor
    elif avg_error > target_error:
        kp *= 1 + 0.10 * error_factor
        ki *= 1 + 0.10 * error_factor
    elif avg_overshoot > target_overshoot:
        kp *= 0.95
        kd *= 1 + 0.15 * overshoot_factor
    kp = max(0.01, min(kp, 1.0))
    ki = max(0.0, min(ki, 0.1))
    kd = max(0.0, min(kd, 0.2))
    return round(kp, 4), round(ki, 4), round(kd, 4)

def _prompt_user(prompt, options=None, default=None):
    """Prompts the user for input with optional validation and default."""
    full_prompt = prompt
    if options:
        full_prompt += f" [{'/'.join(options)}, default {default}]"
    else:
        full_prompt += f" [default: {default}]"
    try:
        user_input = input(full_prompt + ": ").strip().upper()
        if not user_input and default is not None:
            return default
        if options and user_input not in options:
            print("Invalid selection.")
            return None
        return user_input
    except EOFError:
        return default

def _select_pid_source(servo, sysconfig, dmesg, default_kp, default_ki, default_kd):
    """Presents PID source options to the user and returns the selected PID values."""
    options_available = ["D"]
    _log("Choose initial PID source:", dmesg)
    _log(f"  (D) Defaults: Kp={default_kp:.4f}, Ki={default_ki:.4f}, Kd={default_kd:.4f}", dmesg)
    if sysconfig:
        sc_kp = sysconfig.get("SERVO.P", "N/A")
        sc_ki = sysconfig.get("SERVO.I", "N/A")
        sc_kd = sysconfig.get("SERVO.D", "N/A")
        sc_kp_str = f"{sc_kp:.4f}" if isinstance(sc_kp, (int, float)) else sc_kp
        sc_ki_str = f"{sc_ki:.4f}" if isinstance(sc_ki, (int, float)) else sc_ki
        sc_kd_str = f"{sc_kd:.4f}" if isinstance(sc_kd, (int, float)) else sc_kd
        _log(f"  (L) Sysconfig: Kp={sc_kp_str}, Ki={sc_ki_str}, Kd={sc_kd_str}", dmesg)
        options_available.append("L")
    else:
        _log("  (L) Sysconfig: Not available.", dmesg)
    if hasattr(servo, 'Kp') and hasattr(servo, 'Ki') and hasattr(servo, 'Kd'):
        _log(f"  (C) Current Servo: Kp={servo.Kp:.4f}, Ki={servo.Ki:.4f}, Kd={servo.Kd:.4f}", dmesg)
        options_available.append("C")
    _log("  (E) Enter values manually", dmesg)
    options_available.append("E")

    choice = _prompt_user("Choice", options=options_available, default="D")
    if choice == "L" and sysconfig:
        kp = sysconfig.get("SERVO.P", default_kp)
        ki = sysconfig.get("SERVO.I", default_ki)
        kd = sysconfig.get("SERVO.D", default_kd)
    elif choice == "C" and hasattr(servo, 'Kp'):
        kp, ki, kd = servo.Kp, servo.Ki, servo.Kd
    elif choice == "E":
        kp, ki, kd = get_pid_values_from_user(default_kp, default_ki, default_kd, dmesg)
    else:
        kp, ki, kd = default_kp, default_ki, default_kd
    return kp, ki, kd

async def _run_test_runs(servo, encoder, dmesg, moves, num_runs):
    """Runs the test sequence multiple times and returns results."""
    all_individual_move_results_across_all_runs = []
    best_runs = []
    for i in range(num_runs):
        run_log_prefix = f"Run {i+1}/{num_runs}: "
        one_run_results = await _run_test_sequence_for_one_iteration(
            servo, encoder, dmesg, moves, log_prefix=run_log_prefix
        )
        all_individual_move_results_across_all_runs.extend(one_run_results)
        run_summary = _summarize_run_results(one_run_results, i + 1, dmesg)
        if run_summary:
            avg_error = run_summary["avg_abs_final_error"] if run_summary["avg_abs_final_error"] is not None else float('inf')
            best_runs.append((
                avg_error,
                {
                    "summary": run_summary,
                }
            ))
            best_runs.sort(key=lambda x: x[0])
            best_runs = best_runs[:3]
        if i < num_runs - 1:
            await asyncio.sleep_ms(_PAUSE_BETWEEN_RUNS_MS)
    return all_individual_move_results_across_all_runs, best_runs

def _calculate_move_summaries(all_individual_move_results_across_all_runs, default_moves):
    """Calculates move summaries for PID tuning."""
    move_summaries = []
    for idx, move in enumerate(default_moves):
        moves = [m for m in all_individual_move_results_across_all_runs if m.get("move_index_in_sequence") == idx and not m.get("timeout")]
        if moves:
            avg_error = sum(abs(m["final_error"]) for m in moves) / len(moves)
            avg_overshoot = sum(m["directional_overshoot"] for m in moves) / len(moves)
        else:
            avg_error = 0
            avg_overshoot = 0
        move_summaries.append({
            "move_idx": idx,
            "avg_abs_final_error": avg_error,
            "avg_directional_overshoot": avg_overshoot,
        })
    return move_summaries

async def run_performance_profiler(app_passthrough):
    """Main entry point for the servo performance profiler."""
    servo = app_passthrough.get('SERVO')
    encoder = app_passthrough.get('ENCODER')
    dmesg = app_passthrough.get('DMESG')
    sysconfig = app_passthrough.get('SYSCONFIG')

    if not servo or not encoder:
        print("PERF_PROFILER: ERROR - SERVO or ENCODER object not found.")
        return

    _log("--- Servo Performance Profiler Initialized ---", dmesg)

    # Ask the user if they want to run the peel motor during the tests
    run_peel_prompt = _prompt_user("Run peel motor during tests?", options=["Y", "N"], default="N")
    run_peel = run_peel_prompt == "Y"
    servo.peel_enable(run_peel)  # Enable or disable peel motor based on user input

    mode = _prompt_user("Select mode: (A)uto-tune, (M)anual, or (P)rofile?", options=["A", "M", "P"], default="A") or "A"

    if mode == "A":
        current_kp, current_ki, current_kd = _select_pid_source(servo, sysconfig, dmesg, _DEFAULT_KP, _DEFAULT_KI, _DEFAULT_KD)
        while True:
            num_runs_to_perform = int(_prompt_user("Enter number of passes per PID set", default=_NUM_TEST_RUNS))
            num_auto_tune_rounds = int(_prompt_user("How many iterative auto-tune rounds?", default=3))

            best_runs = []
            for auto_round in range(num_auto_tune_rounds):
                _log(f"Auto-tune round {auto_round+1}/{num_auto_tune_rounds}: Kp={current_kp:.4f}, Ki={current_ki:.4f}, Kd={current_kd:.4f}", dmesg)
                servo.Kp = current_kp
                servo.Ki = current_ki
                servo.Kd = current_kd
                all_individual_move_results_across_all_runs, round_best_runs = await _run_test_runs(servo, encoder, dmesg, _DEFAULT_MOVES, num_runs_to_perform)
                best_runs.extend((score, {"pid": (current_kp, current_ki, current_kd), "run_number": f"Auto{auto_round+1}-{i+1}", "summary": info["summary"]}) for i, (score, info) in enumerate(round_best_runs))
                best_runs.sort(key=lambda x: x[0])
                best_runs = best_runs[:3]
                _calculate_and_log_average_per_move_type(all_individual_move_results_across_all_runs, _DEFAULT_MOVES, dmesg)
                move_summaries = _calculate_move_summaries(all_individual_move_results_across_all_runs, _DEFAULT_MOVES)
                current_kp, current_ki, current_kd = suggest_pid_from_results(current_kp, current_ki, current_kd, move_summaries)

            print("\n=== Top 3 Best Runs (Lowest Avg Abs Final Error) ===")
            for idx, (score, info) in enumerate(best_runs, 1):
                kp, ki, kd = info["pid"]
                run_num = info["run_number"]
                summary = info["summary"]
                print(f"#{idx}: Run={run_num}, PID=({kp:.4f}, {ki:.4f}, {kd:.4f}), Avg Error={score:.2f}, Max Overshoot={summary['max_directional_overshoot']:.2f}, Moves Completed={summary['moves_completed']}/{summary['total_moves_in_sequence']}")

            while True:
                print("\nSelect which PID values to use for next run or save:")
                for idx, (score, info) in enumerate(best_runs, 1):
                    kp, ki, kd = info["pid"]
                    print(f"  ({idx}) PID=({kp:.4f}, {ki:.4f}, {kd:.4f})")
                print("  (R) Re-run iterative test")
                print("  (S) Save current values and exit [default: 1]")
                selection = _prompt_user("Enter 1/2/3/R/S", options=["1", "2", "3", "R", "S"], default="1")
                if selection in ("1", "2", "3"):
                    idx = int(selection) - 1
                    current_kp, current_ki, current_kd = best_runs[idx][1]["pid"]
                    servo.Kp = current_kp
                    servo.Ki = current_ki
                    servo.Kd = current_kd
                    break
                elif selection == "R":
                    break
                elif selection == "S":
                    break
                else:
                    print("Invalid selection.")
            if selection == "R":
                continue
            else:
                break

        if sysconfig:
            sysconfig.set("SERVO.P", current_kp)
            sysconfig.set("SERVO.I", current_ki)
            sysconfig.set("SERVO.D", current_kd)
            sysconfig.save()
            _log("PID values saved to sysconfig.", dmesg)
        servo.Kp = current_kp
        servo.Ki = current_ki
        servo.Kd = current_kd
        _log("--- Servo Performance Profiler Finished ---", dmesg)
        return

    elif mode == "M":
        current_kp, current_ki, current_kd = _select_pid_source(servo, sysconfig, dmesg, _DEFAULT_KP, _DEFAULT_KI, _DEFAULT_KD)
        while True:
            num_runs_to_perform = int(_prompt_user("Enter number of test runs", default=_NUM_TEST_RUNS))
            all_individual_move_results_across_all_runs, best_runs = await _run_test_runs(servo, encoder, dmesg, _DEFAULT_MOVES, num_runs_to_perform)
            _log(f"Preparing for {num_runs_to_perform} test runs.", dmesg)
            _log(f"Current PID: Kp={current_kp:.4f}, Ki={current_ki:.4f}, Kd={current_kd:.4f}", dmesg)
            servo.Kp = current_kp
            servo.Ki = current_ki
            servo.Kd = current_kd

            print("\n=== Manual Test Summary ===")
            for idx, (score, info) in enumerate(best_runs, 1):
                summary = info["summary"]
                print(f"#{idx}: Run={idx}, Avg Error={score:.2f}, Max Overshoot={summary['max_directional_overshoot_in_run']:.2f}, Moves Completed={summary['moves_completed']}/{summary['total_moves_in_sequence']}")

            while True:
                print("\n  (S) Save these PID values and exit")
                print("  (E) Enter new PID values (defaults to suggested)")
                print("  (R) Re-run test with new values")
                print("  (X) Exit without saving")
                selection = _prompt_user("Enter S/E/R/X", options=["S", "E", "R", "X"], default="S")
                if selection == "S":
                    break
                elif selection == "X":
                    return  # Exit the profiler immediately
                elif selection in ("E", "R"):
                    move_summaries = _calculate_move_summaries(all_individual_move_results_across_all_runs, _DEFAULT_MOVES)
                    suggested_kp, suggested_ki, suggested_kd = suggest_pid_from_results(current_kp, current_ki, current_kd, move_summaries)
                    current_kp, current_ki, current_kd = get_pid_values_from_user(suggested_kp, suggested_ki, suggested_kd, dmesg)
                    servo.Kp = current_kp
                    servo.Ki = current_ki
                    servo.Kd = current_kd
                    break
                else:
                    print("Invalid selection.")
            if selection == "S":
                break

        if sysconfig:
            sysconfig.set("SERVO.P", current_kp)
            sysconfig.set("SERVO.I", current_ki)
            sysconfig.set("SERVO.D", current_kd)
            sysconfig.save()
            _log("PID values saved to sysconfig.", dmesg)
        servo.Kp = current_kp
        servo.Ki = current_ki
        servo.Kd = current_kd
        _log("--- Servo Performance Profiler Finished ---", dmesg)
        return

    elif mode == "P":
        global _PROFILE_RUNS, _PROFILE_TICKS
        use_suggested_next = False
        suggested_kp, suggested_ki, suggested_kd = _DEFAULT_KP, _DEFAULT_KI, _DEFAULT_KD
        current_kp, current_ki, current_kd = _DEFAULT_KP, _DEFAULT_KI, _DEFAULT_KD
        while True:
            if use_suggested_next:
                current_kp, current_ki, current_kd = suggested_kp, suggested_ki, suggested_kd
                use_suggested_next = False
                print(f"\nUsing suggested PID values: Kp={current_kp:.4f}, Ki={current_ki:.4f}, Kd={current_kd:.4f}")
                num_profile_runs = _PROFILE_RUNS
                profile_ticks = _PROFILE_TICKS
            else:
                current_kp, current_ki, current_kd = _select_pid_source(servo, sysconfig, dmesg, _DEFAULT_KP, _DEFAULT_KI, _DEFAULT_KD)
                num_profile_runs = int(_prompt_user("How many profile test runs?", default=_PROFILE_RUNS))
                profile_ticks = int(_prompt_user("How many ticks per move?", default=_PROFILE_TICKS))
                _PROFILE_RUNS = num_profile_runs
                _PROFILE_TICKS = profile_ticks

            servo.Kp = current_kp
            servo.Ki = current_ki
            servo.Kd = current_kd

            count = 0
            sum_settling = 0.0
            sum_settling2 = 0.0
            min_settling = None
            max_settling = None
            sum_error = 0.0
            sum_error2 = 0.0
            min_error = None
            max_error = None
            sum_overshoot = 0.0
            sum_overshoot2 = 0.0
            min_overshoot = None
            max_overshoot = None
            num_timeouts = 0

            for i in range(num_profile_runs):
                run_log_prefix = f"Profile Run {i+1}/{num_profile_runs}: "
                one_run_results = await _run_test_sequence_for_one_iteration(
                    servo, encoder, dmesg, [profile_ticks], log_prefix=run_log_prefix
                )
                move = one_run_results[0]
                count += 1
                settling = move.get("settling_time_s", 0)
                error = abs(move.get("final_error", 0))
                overshoot = abs(move.get("directional_overshoot", 0))
                timeout = move.get("timeout", False)
                sum_settling += settling
                sum_settling2 += settling * settling
                min_settling = settling if min_settling is None else min(min_settling, settling)
                max_settling = settling if max_settling is None else max(max_settling, settling)

                sum_error += error
                sum_error2 += error * error
                min_error = error if min_error is None else min(min_error, error)
                max_error = error if max_error is None else max(max_error, error)

                sum_overshoot += overshoot
                sum_overshoot2 += overshoot * overshoot
                min_overshoot = overshoot if min_overshoot is None else min(min_overshoot, overshoot)
                max_overshoot = overshoot if max_overshoot is None else max(max_overshoot, overshoot)

                if timeout:
                    num_timeouts += 1

                await asyncio.sleep_ms(_PAUSE_BETWEEN_RUNS_MS)

            def mean(s, n): return s / n if n else 0
            def stddev(s, s2, n): return ((s2 / n - (s / n) ** 2) ** 0.5) if n else 0

            print("\nProfile test complete. Stats:")
            print(f"  Runs: {count}, Timeouts: {num_timeouts}")
            print(f"  Settling Time (s): Avg={mean(sum_settling, count):.3f}, Min={min_settling:.3f}, Max={max_settling:.3f}, StdDev={stddev(sum_settling, sum_settling2, count):.3f}")
            print(f"  Abs Final Error (ticks): Avg={mean(sum_error, count):.2f}, Min={min_error:.2f}, Max={max_error:.2f}, StdDev={stddev(sum_error, sum_error2, count):.2f}")
            print(f"  Dir. Overshoot (ticks): Avg={mean(sum_overshoot, count):.2f}, Min={min_overshoot:.2f}, Max={max_overshoot:.2f}, StdDev={stddev(sum_overshoot, sum_overshoot2, count):.2f}")

            move_summaries = [{
                "move_idx": 0,
                "avg_abs_final_error": mean(sum_error, count),
                "avg_directional_overshoot": mean(sum_overshoot, count),
            }]
            suggested_kp, suggested_ki, suggested_kd = suggest_pid_from_results(current_kp, current_ki, current_kd, move_summaries)
            print(f"\nSuggested PID values based on profile results: Kp={suggested_kp:.4f}, Ki={suggested_ki:.4f}, Kd={suggested_kd:.4f}")

            try:
                again = input("Start a new profile test? (Y)es/(N)o [default N]: ").strip().upper()
            except EOFError:
                again = "N"
            if again == "Y":
                try:
                    use_suggested = input("Use suggested PID values for next test? (Y)es/(N)o [default N]: ").strip().upper()
                except EOFError:
                    use_suggested = "N"
                if use_suggested == "Y":
                    use_suggested_next = True
                continue
            else:
                try:
                    save_pid = input("Save these PID values to sysconfig and servo before exit? (Y)es/(N)o [default N]: ").strip().upper()
                except EOFError:
                    save_pid = "N"
                if save_pid == "Y":
                    if sysconfig:
                        sysconfig.set("SERVO.P", current_kp)
                        sysconfig.set("SERVO.I", current_ki)
                        sysconfig.set("SERVO.D", current_kd)
                        sysconfig.save()
                        _log("PID values saved to sysconfig.", dmesg)
                    servo.Kp = current_kp
                    servo.Ki = current_ki
                    servo.Kd = current_kd
                    _log("PID values set on servo.", dmesg)
                _log("--- Servo Performance Profiler Finished ---", dmesg)
                return
