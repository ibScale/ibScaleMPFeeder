# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# profiler.py - Auto-tuner for the profile-based software servo.
#
# The servo positions by stopping repeatably at a slow terminal CREEP speed rather
# than by PID gains, so the things worth tuning are:
#   CREEP        - terminal approach speed; the dominant knob for stop repeatability.
#   CREEP_TICKS  - how long the slow tail is held; longer absorbs more momentum (less overshoot).
#
# Strategy: oscillate the drive back and forth around a start point (bounded travel),
# measuring the stop error of repeated FORWARD moves. Sweep CREEP from fast to slow,
# score each batch by repeatability (std), bias (|mean|), overshoot and faults, then
# pick the slowest reliable value with no overshoot. If overshoot persists, lengthen
# CREEP_TICKS. Apply to the live servo and optionally persist to sysconfig.

import asyncio
import time
from system.servo import RESULT_REACHED, RESULT_OVERSHOT, RESULT_STALLED, RESULT_TIMEOUT
from system.watchdog import feed as wdt_feed

# Standard EIA-481 carrier-tape pitches (mm) that real feeds use. The chosen tuning
# is validated at each so per-package behaviour (0402->2mm, 0603/0805->4mm,
# SOT-23->8mm, SOT-223->12mm, ...) is measured rather than assumed.
_STANDARD_PITCHES_MM = (2, 4, 8, 12)


def _log(dmesg, msg):
    full = f"PROFILER: {msg}"
    if dmesg and hasattr(dmesg, 'log'):
        dmesg.log(full)
    else:
        print(full)


async def _run_move(servo, target, loop_ms, max_ms):
    """Issue a move to an absolute target and pump update() until done or timed out."""
    servo.set_target(target)
    start = time.ticks_ms()
    while servo.is_busy:
        servo.update()
        wdt_feed()
        if time.ticks_diff(time.ticks_ms(), start) > max_ms:
            break
        await asyncio.sleep_ms(loop_ms)
    elapsed = time.ticks_diff(time.ticks_ms(), start)
    pos = servo.get_current_position()
    return {'result': servo.result, 'error': pos - target, 'elapsed': elapsed}


def _summarize(samples):
    """Reduce a list of per-move dicts to a metrics dict."""
    n = len(samples)
    errors = [s['error'] for s in samples]
    mean = sum(errors) / n
    var = sum((e - mean) ** 2 for e in errors) / n
    return {
        'n': n,
        'reached': sum(1 for s in samples if s['result'] == RESULT_REACHED),
        'overshoot': sum(1 for s in samples if s['result'] == RESULT_OVERSHOT),
        'fault': sum(1 for s in samples if s['result'] in (RESULT_STALLED, RESULT_TIMEOUT)),
        'mean': mean,
        'std': var ** 0.5,
        'abs_mean': sum(abs(e) for e in errors) / n,
        'emin': min(errors),
        'emax': max(errors),
        't_mean': sum(s['elapsed'] for s in samples) / n,
    }


def _score(m):
    """Lower is better. None if the batch had a fault (unusable)."""
    if m['fault'] > 0:
        return None
    overshoot_rate = m['overshoot'] / m['n']
    # Overshoot dominates (we can't reverse to fix it); then repeatability, then bias.
    return m['std'] + 0.5 * m['abs_mean'] + overshoot_rate * 100.0


async def _measure(servo, start_pos, distance, samples, loop_ms, max_ms):
    """Run `samples` forward moves of `distance`, repositioning back to start between them."""
    data = []
    for _ in range(samples):
        data.append(await _run_move(servo, start_pos + distance, loop_ms, max_ms))
        # Reposition back to start (not measured). Reverse move ends forward, so the
        # next measured move starts from a consistent, backlash-taken-up condition.
        await _run_move(servo, start_pos, loop_ms, max_ms)
    return _summarize(data)


def _creep_candidates(servo):
    """Spread of CREEP speeds from fast down to the floor, within [MIN, MAX]."""
    hi = min(int(servo.max_output * 0.5), 40)
    lo = max(servo.min_output, 6)
    if hi <= lo:
        hi = lo + 6
    step = max(2, (hi - lo) // 6)
    vals = []
    v = hi
    while v >= lo:
        vals.append(v)
        v -= step
    if lo not in vals:
        vals.append(lo)
    return vals  # descending (fast -> slow)


def _report_row(dmesg, label, m):
    if m['fault']:
        _log(dmesg, f"  {label}: FAULTED ({m['fault']}/{m['n']}) - unusable")
    else:
        _log(dmesg, f"  {label}: err mean={m['mean']:.1f} std={m['std']:.1f} "
                    f"[{m['emin']}..{m['emax']}], overshoot={m['overshoot']}/{m['n']}, "
                    f"t={m['t_mean']:.0f}ms")


async def _validate_pitches(servo, sysconfig, dmesg, start_pos, loop_ms, max_ms, samples=4):
    """Exercise the current tuning at the standard tape pitches and flag bad geometry.

    The terminal stop (CREEP tail + brake) is pitch-independent, but a pitch shorter
    than DECEL_TICKS + CREEP_TICKS never reaches cruise, so those feeds run slow.
    The accuracy invariant is that the fixed creep tail must fit inside the pitch.
    """
    ticks_per_mm = sysconfig.get('SYSTEM.TICKS_010MM', 22.546) * 10
    geometry = servo.decel_ticks + servo.creep_ticks  # distance needed to reach cruise
    creep_floor = servo.creep_ticks + servo.tolerance  # the stop tail that must fit
    pitches = sysconfig.get('SERVO.VALIDATE_PITCHES_MM', _STANDARD_PITCHES_MM)

    _log(dmesg, "Validating at standard tape pitches:")
    for pitch_mm in pitches:
        pitch_ticks = int(pitch_mm * ticks_per_mm)
        if pitch_ticks <= servo.tolerance:
            continue
        m = await _measure(servo, start_pos, pitch_ticks, samples, loop_ms, max_ms)
        _report_row(dmesg, f"{pitch_mm}mm ({pitch_ticks}t)", m)
        if pitch_ticks < creep_floor:
            _log(dmesg, f"    WARNING: creep tail ({creep_floor}t) does not fit a {pitch_mm}mm pitch "
                        "- stop accuracy may degrade for this package.")
        elif pitch_ticks < geometry:
            _log(dmesg, f"    NOTE: {pitch_mm}mm < decel+creep ({geometry}t) - this feed never reaches "
                        "full speed (slower throughput, accuracy unaffected).")


async def run_performance_profiler(app_passthrough):
    """Entry point (kept for the recovery menu / misc.profiler_test)."""
    if not isinstance(app_passthrough, dict):
        print("PROFILER: invalid app_passthrough")
        return
    dmesg = app_passthrough.get('DMESG')
    servo = app_passthrough.get('SERVO')
    sysconfig = app_passthrough.get('SYSCONFIG')
    if not servo or not sysconfig:
        _log(dmesg, "SERVO/SYSCONFIG missing - cannot run.")
        return

    loop_ms = sysconfig.get('APP.LOOP_INTERVAL_MS', 20)
    max_ms = servo.move_timeout_ms + 1000
    samples = 6
    # Distance long enough to exercise the full accel/cruise/decel/creep profile.
    distance = servo.accel_ticks + servo.decel_ticks + servo.creep_ticks + max(50, servo.tolerance * 4)

    # Preserve originals so we can restore on decline/abort.
    orig = {
        'creep': servo.creep_output,
        'creep_ticks': servo.creep_ticks,
        'peel': servo.peel_motor_enabled_by_servo,
    }

    _log(dmesg, "=== Servo auto-tune ===")
    _log(dmesg, f"Bounded oscillation of ~{distance} ticks, {samples} samples/step, loop={loop_ms}ms.")
    _log(dmesg, "Ensure the carriage can travel freely. Peel motor disabled during tuning.")

    servo.peel_enable(False)
    try:
        servo.enable(True)
        start_pos = servo.get_current_position()

        # Sanity move: confirm the drive actually moves forward.
        probe = await _run_move(servo, start_pos + distance, loop_ms, max_ms)
        await _run_move(servo, start_pos, loop_ms, max_ms)
        if probe['result'] in (RESULT_STALLED, RESULT_TIMEOUT) or abs(probe['error']) > distance:
            _log(dmesg, f"Probe move failed (result={servo.result_name}, err={probe['error']}). "
                        "Check power/wiring/direction. Aborting.")
            return

        # --- Sweep CREEP -------------------------------------------------
        _log(dmesg, "Sweeping CREEP (fast -> slow):")
        results = []  # (creep, metrics)
        for creep in _creep_candidates(servo):
            servo.creep_output = creep
            m = await _measure(servo, start_pos, distance, samples, loop_ms, max_ms)
            results.append((creep, m))
            _report_row(dmesg, f"CREEP={creep}", m)

        # Pick the best-scoring fault-free batch; tie-break toward the slower (lower) creep.
        best = None  # (score, creep, metrics)
        for creep, m in results:
            s = _score(m)
            if s is None:
                continue
            if best is None or s < best[0] - 0.01 or (abs(s - best[0]) <= 0.01 and creep < best[1]):
                best = (s, creep, m)

        if best is None:
            _log(dmesg, "No reliable CREEP found (every step faulted). "
                        "Raise MIN or check the mechanism. Restoring originals.")
            servo.creep_output = orig['creep']
            return

        best_creep, best_m = best[1], best[2]
        servo.creep_output = best_creep
        _log(dmesg, f"Selected CREEP={best_creep} (std={best_m['std']:.1f}, overshoot={best_m['overshoot']}/{best_m['n']}).")

        # --- Refine CREEP_TICKS if overshoot remains ---------------------
        best_creep_ticks = orig['creep_ticks']
        if best_m['overshoot'] > 0:
            _log(dmesg, "Overshoot present - lengthening CREEP_TICKS:")
            for mult in (1.5, 2.0, 2.5):
                ct = int(orig['creep_ticks'] * mult)
                servo.creep_ticks = ct
                m = await _measure(servo, start_pos, distance, samples, loop_ms, max_ms)
                _report_row(dmesg, f"CREEP_TICKS={ct}", m)
                if m['fault'] == 0 and m['overshoot'] == 0:
                    best_creep_ticks = ct
                    best_m = m
                    break
            else:
                _log(dmesg, "Overshoot persists; also consider lowering MAX.")
                best_creep_ticks = servo.creep_ticks
            servo.creep_ticks = best_creep_ticks

        _log(dmesg, "=== Recommendation ===")
        _log(dmesg, f"CREEP={best_creep}, CREEP_TICKS={best_creep_ticks} "
                    f"(err std={best_m['std']:.1f}, bias={best_m['mean']:.1f}, "
                    f"overshoot={best_m['overshoot']}/{best_m['n']})")

        # --- Validate across standard tape pitches -----------------------
        await _validate_pitches(servo, sysconfig, dmesg, start_pos, loop_ms, max_ms)

        # --- Persist? ----------------------------------------------------
        try:
            ans = input("Save to sysconfig and apply? (Y/n): ").strip().lower()
        except Exception:
            ans = 'y'  # headless: persist by default

        if ans in ('', 'y', 'yes'):
            sysconfig.set('SERVO.CREEP', best_creep)
            sysconfig.set('SERVO.CREEP_TICKS', best_creep_ticks)
            sysconfig.save()
            # Live servo already holds best_creep / best_creep_ticks.
            _log(dmesg, "Saved and applied.")
        else:
            servo.creep_output = orig['creep']
            servo.creep_ticks = orig['creep_ticks']
            _log(dmesg, "Discarded; servo restored to previous values.")

    except Exception as e:
        _log(dmesg, f"ERROR during tuning: {e}")
        servo.creep_output = orig['creep']
        servo.creep_ticks = orig['creep_ticks']
    finally:
        servo.peel_enable(orig['peel'])
        servo.disable()
        _log(dmesg, "Auto-tune finished.")
