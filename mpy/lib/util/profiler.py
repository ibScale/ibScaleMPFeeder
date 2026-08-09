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
# The operator loads a REAL tape and the tuner measures the production code path
# against it: every trial is a servo.feed() (cumulative grid targeting, this slot's
# speed profile) run to completion with servo.run_move() (real-time burst) - exactly
# what a Photon MOVE_FEED or button jog does - at the loaded tape's pitch, with the
# peel motor running as it would in production. Sweep CREEP from fast to slow, score
# each batch by repeatability (std), bias (|mean|), overshoot and faults, then pick
# the slowest reliable value with no overshoot. A stall at any CREEP disqualifies that
# speed AND every slower one tested afterward, even if a later batch looks clean - a
# slower creep only has less momentum to work with, so it's assumed at least as
# stall-prone rather than trusting a small sample that got lucky. If overshoot
# persists, lengthen CREEP_TICKS. Apply to the live servo and optionally persist to
# sysconfig.
#
# Moves are strictly FORWARD - tape can't be rewound through the mechanism. feed()
# would only ever plan a reverse if a previous overshoot pushed the actual position
# past the next grid target; the tuner re-anchors the grid (reseed) instead when
# that happens. The whole run consumes real tape - see the "will advance" estimate
# logged before the sweep starts.

import time
import sys
import select
from system.servo import RESULT_REACHED, RESULT_OVERSHOT, RESULT_STALLED, RESULT_TIMEOUT
from system.watchdog import feed as wdt_feed

_DEFAULT_PITCH_MM = 4  # most common EIA-481 pitch (0603/0805, SOT-23 singles, ...)
_DWELL_MS = 100        # at-rest pause between feed cycles (the "pick" phase of a real
                       # SMD cycle); servo.update() is pumped throughout, like the app
                       # loop. Note: shorter than POST_PEEL_MS (200), so the peel stop
                       # stays pending and the next feed simply re-drives the peel.
_MAX_CONSEC_FAULTS = 3  # stalls/timeouts in a row that end the batch AND the sweep


def _log(dmesg, msg):
    full = f"PROFILER: {msg}"
    if dmesg and hasattr(dmesg, 'log'):
        dmesg.log(full)
    else:
        print(full)


def _input(prompt):
    """Blocking line input that keeps the watchdog fed while waiting (the IWDG can't
    be paused, and an operator can easily out-wait it at a prompt)."""
    print(prompt, end='')
    poller = select.poll()
    poller.register(sys.stdin, select.POLLIN)
    while True:
        wdt_feed()
        if poller.poll(200):
            line = sys.stdin.readline()
            if line is None:
                return ''
            line = line.strip()
            print(line)  # echo
            return line


def _dwell(servo, ms):
    """Rest between feeds, pumping servo.update() at the app-loop rate exactly like
    the production main loop does after a move: this is what services the deferred
    post-peel stop (POST_PEEL_MS after the drive brakes), and it puts a real
    at-rest gap between feeds like the pick phase of an SMD cycle. Without it the
    sweep runs feeds back-to-back and the mechanism never visibly stops."""
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < ms:
        servo.update()
        wdt_feed()
        time.sleep_ms(20)


def _run_feed(servo, dmesg, distance, profile, dwell_ms=_DWELL_MS):
    """One production-path feed: grid-targeted move of `distance` ticks run as a
    real-time burst, same as a Photon MOVE_FEED, followed by an at-rest dwell.
    Returns a per-move sample dict (elapsed covers the move only, not the dwell).

    Forward-only guard: if a previous overshoot carried the actual position to (or
    past) the next grid target, honoring the grid would mean reversing - which would
    pull real tape backward - so re-anchor the grid to reality and feed from here.
    """
    cur = servo.get_current_position()
    if servo.commanded_position + distance <= cur + servo.tolerance:
        servo.reseed()
        _log(dmesg, f"  (overshoot consumed the next pitch - grid re-anchored at {cur})")
    start = time.ticks_ms()
    target = servo.feed(distance, profile=profile)
    result = servo.run_move()
    elapsed = time.ticks_diff(time.ticks_ms(), start)
    err = servo.get_current_position() - target
    if result == RESULT_STALLED or result == RESULT_TIMEOUT:
        # A faulted feed leaves the commanded grid ahead of reality; re-anchor so
        # the next trial is a clean single-pitch feed instead of an ever-growing
        # catch-up move (mirrors what Photon does after a fault).
        servo.reseed()
    _dwell(servo, dwell_ms)
    return {'result': result, 'error': err, 'elapsed': elapsed}


def _measure(servo, dmesg, distance, samples, profile, dwell_ms=_DWELL_MS):
    """Run `samples` production feed/stop cycles (forward-only) and summarize.

    Bails out of the batch after _MAX_CONSEC_FAULTS stalls/timeouts in a row and
    marks the metrics 'aborted' - by then the candidate is proven unusable, and
    every remaining sample would just grind the same stall."""
    data = []
    consec = 0
    for _ in range(samples):
        s = _run_feed(servo, dmesg, distance, profile, dwell_ms)
        data.append(s)
        if s['result'] in (RESULT_STALLED, RESULT_TIMEOUT):
            consec += 1
            if consec >= _MAX_CONSEC_FAULTS:
                break
        else:
            consec = 0
    m = _summarize(data)
    m['aborted'] = consec >= _MAX_CONSEC_FAULTS
    return m


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
    """Lower is better. None if the batch had a fault, or a faster CREEP in the same
    sweep already faulted - stalling isn't a fluke of that one speed, and slower CREEP
    only has less momentum to work with, so it's assumed at least as stall-prone and
    disqualified along with it rather than risking picking it off a lucky small sample."""
    if m['fault'] > 0 or m.get('disqualified'):
        return None
    overshoot_rate = m['overshoot'] / m['n']
    # Overshoot dominates (we can't reverse to fix it); then repeatability, then bias.
    return m['std'] + 0.5 * m['abs_mean'] + overshoot_rate * 100.0


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
        _log(dmesg, f"  {label}: err mean={m['mean']:.1f} std={m['std']:.1f} " +
                    f"[{m['emin']}..{m['emax']}], overshoot={m['overshoot']}/{m['n']}, " +
                    f"t={m['t_mean']:.0f}ms")


def _offer_rewind(servo, dmesg, start_pos, ticks_per_mm):
    """Report total tape consumed and offer to run it back to the starting position.

    Tuning is done on a real tape, usually still attached to its reel - rewinding
    what the run consumed makes unloading the feeder (or just re-tensioning the reel)
    much easier. Measured from actual encoder travel, so it includes the probe feed,
    every sweep sample, and any overshoot.
    """
    end_pos = servo.get_current_position()
    total_ticks = end_pos - start_pos
    if total_ticks <= 0:
        return
    _log(dmesg, f"Total tape consumed: {total_ticks} ticks (~{total_ticks / ticks_per_mm:.0f}mm).")
    try:
        ans = _input("Rewind tape to the starting position? (y/N): ").lower()
    except Exception:
        return  # headless / no stdin: leave the tape where it is
    if ans not in ('y', 'yes'):
        return
    _log(dmesg, "Rewinding (reverse, then forward re-approach to the start point)...")
    # Real reverse move: backoff runs slightly PAST the start point, then the normal
    # forward approach lands on it. No per-move time cap (the distance can be long);
    # stall detection stays active so a snagged tape faults instead of grinding, and
    # run_move gets a distance-scaled backstop instead of its default ~11s one.
    servo.set_target(start_pos, timeout_ms=0)
    servo.run_move(max_ms=10000 + 2 * total_ticks)
    _log(dmesg, f"Rewind: {servo.result_name} at {servo.get_current_position()} (start was {start_pos}).")
    servo.reseed()  # position moved a long way; re-anchor the grid for the app


def _explain_choice(dmesg, results, best_creep, best_m, ticks_per_mm):
    """Spell out in physical units why the winning CREEP was chosen, so the operator
    can sanity-check the tuner's judgement instead of trusting a bare score."""
    um = 1000.0 / ticks_per_mm      # um per encoder tick
    scored = sorted((s, c) for c, m in results if (s := _score(m)) is not None)
    faulted = len(results) - len(scored)
    # Keep each line short: long dmesg lines get clipped on narrow consoles.
    why = f"Why CREEP={best_creep}: best of {len(scored)} usable"
    if len(scored) > 1:
        why += f" (score {scored[0][0]:.1f} vs {scored[1][0]:.1f} next-best CREEP={scored[1][1]})"
    if faulted:
        why += f"; {faulted} faulted"
    _log(dmesg, why + ".")
    _log(dmesg, f"  Repeatability: std {best_m['std']:.1f}t (~+/-{best_m['std'] * um:.0f}um) - " +
                "the error feeds can't correct; the deciding number.")
    side = 'short' if best_m['mean'] < 0 else 'past'
    _log(dmesg, f"  Bias: {abs(best_m['mean']):.1f}t (~{abs(best_m['mean']) * um:.0f}um) {side} " +
                "on average - harmless, grid targeting absorbs it.")
    _log(dmesg, f"  Overshoot: {best_m['overshoot']}/{best_m['n']} - can't be backed out " +
                "(forward-only); zero required.")
    _log(dmesg, f"  Throughput: ~{best_m['t_mean']:.0f}ms per feed at this CREEP.")


def _geometry_notes(servo, dmesg, pitch_ticks, pitch_mm):
    """Arithmetic sanity check of the tuned geometry against the loaded pitch. The
    terminal stop (CREEP tail + brake) is pitch-independent, so this needs no extra
    tape-consuming moves - the accuracy invariant is simply that the fixed creep
    tail must fit inside the pitch."""
    creep_floor = servo.creep_ticks + servo.tolerance
    cruise_dist = servo.decel_ticks + servo.creep_ticks  # distance needed to reach cruise
    if pitch_ticks < creep_floor:
        _log(dmesg, f"WARNING: creep tail ({creep_floor}t) does not fit the {pitch_mm}mm pitch " +
                    "- stop accuracy may degrade. Consider a shorter CREEP_TICKS.")
    elif pitch_ticks < cruise_dist:
        _log(dmesg, f"NOTE: {pitch_mm}mm pitch < decel+creep ({cruise_dist}t) - feeds never reach " +
                    "full speed (slower throughput, accuracy unaffected).")


async def run_performance_profiler(app_passthrough):
    """Entry point (async for the console / misc.profiler_test callers; the tuning
    itself runs blocking real-time bursts, exactly like production feeds)."""
    if not isinstance(app_passthrough, dict):
        print("PROFILER: invalid app_passthrough")
        return
    dmesg = app_passthrough.get('DMESG')
    servo = app_passthrough.get('SERVO')
    sysconfig = app_passthrough.get('SYSCONFIG')
    if not servo or not sysconfig:
        _log(dmesg, "SERVO/SYSCONFIG missing - cannot run.")
        return

    slot_profile = sysconfig.get('APP.SLOT_PROFILE', 'normal')
    ticks_per_mm = sysconfig.get('SYSTEM.TICKS_010MM', 22.546) * 10
    samples = 6

    # The loaded tape's pitch is the tuning distance, so every trial matches this
    # slot's production feeds exactly.
    try:
        raw = _input(f"Tape pitch in mm [{_DEFAULT_PITCH_MM}]: ")
        pitch_mm = float(raw) if raw else _DEFAULT_PITCH_MM
    except Exception:
        pitch_mm = _DEFAULT_PITCH_MM  # headless / no stdin
    distance = int(pitch_mm * ticks_per_mm)

    # Stop-confirmation window in ticks - how close counts as "reached" (a landing
    # farther out than this scores as overshoot). Defaults to the live SERVO.TOLERANCE
    # from sysconfig; let the operator try a tighter/looser window for this run
    # without hand-editing sysconfig first.
    orig_tolerance = servo.tolerance
    try:
        raw = _input(f"Servo tolerance in ticks [{servo.tolerance}]: ")
        if raw:
            servo.tolerance = abs(int(raw))
    except Exception:
        pass  # headless / no stdin / bad input: keep the sysconfig default

    if distance <= servo.tolerance:
        _log(dmesg, f"Pitch {pitch_mm}mm ({distance}t) is within TOLERANCE ({servo.tolerance}t) - nothing to tune.")
        servo.tolerance = orig_tolerance
        return

    # Peel motor: default to production behavior, but let the operator turn it off
    # (e.g. no cover film attached, or tuning a bare mechanism on the bench).
    try:
        raw = _input("Run peel motor during profiling? (Y/n): ").lower()
    except Exception:
        raw = 'y'  # headless / no stdin
    peel_on = raw not in ('n', 'no')

    # Preserve originals so we can restore on decline/abort.
    orig = {'creep': servo.creep_output, 'creep_ticks': servo.creep_ticks,
            'peel': servo.peel_motor_enabled_by_servo, 'tolerance': orig_tolerance}
    servo.peel_enable(peel_on)

    # Worst-case forward travel estimate (probe + CREEP sweep + CREEP_TICKS refine)
    # so the operator knows how much tape this will consume.
    n_creep = len(_creep_candidates(servo))
    worst_ticks = distance * (1 + n_creep * samples + 3 * samples)
    worst_mm = worst_ticks / ticks_per_mm

    _log(dmesg, "=== Servo auto-tune ===")
    peel_desc = 'ON' if peel_on else 'OFF'
    _log(dmesg, f"Production-path feeds: {pitch_mm}mm ({distance}t) each, profile '{slot_profile}', " +
                f"{samples} samples/step, {_DWELL_MS}ms dwell between feeds, peel {peel_desc}, " +
                f"tolerance {servo.tolerance}t.")
    _log(dmesg, f"Forward-only - tape will advance up to ~{worst_ticks} ticks (~{worst_mm:.0f}mm). " +
                "Ensure enough tape is loaded.")

    try:
        servo.enable(True)
        servo.reseed()  # anchor the commanded grid to the actual position, like INITIALIZE does
        start_pos = servo.get_current_position()  # rewind point / total-travel reference

        # Sanity feed: confirm the drive actually moves forward before sweeping.
        probe = _run_feed(servo, dmesg, distance, slot_profile)
        if probe['result'] in (RESULT_STALLED, RESULT_TIMEOUT) or abs(probe['error']) > distance:
            _log(dmesg, f"Probe feed failed (result={servo.result_name}, err={probe['error']}). " +
                        "Check power/wiring/direction/tape path. Aborting.")
            return

        # --- Sweep CREEP -------------------------------------------------
        _log(dmesg, "Sweeping CREEP (fast -> slow):")
        results = []  # (creep, metrics)
        fault_floor_hit = False
        for creep in _creep_candidates(servo):
            servo.creep_output = creep  # set_target() re-derives its ramp from this every move
            m = _measure(servo, dmesg, distance, samples, slot_profile)
            if fault_floor_hit:
                # A faster CREEP already stalled this sweep - every slower one is
                # disqualified too, even if this particular batch came back clean.
                m['disqualified'] = True
            results.append((creep, m))
            _report_row(dmesg, f"CREEP={creep}", m)
            if m['fault'] > 0 and not fault_floor_hit:
                fault_floor_hit = True
                _log(dmesg, f"CREEP={creep} stalled - disqualifying it and every slower CREEP tested from here.")
            if m['aborted'] or m['fault'] == m['n']:
                # The sweep runs fast -> slow, so once a candidate stalls repeatedly
                # every slower one will only fault harder - stop wasting tape.
                _log(dmesg, f"{_MAX_CONSEC_FAULTS} stalls in a row - CREEP floor reached, ending sweep.")
                _log(dmesg, "(If stalls sat at a FIXED position, suspect a jam - check tape path.)")
                break

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
                servo.set_creep_ticks(ct)
                m = _measure(servo, dmesg, distance, samples, slot_profile)
                _report_row(dmesg, f"CREEP_TICKS={ct}", m)
                if m['aborted']:
                    _log(dmesg, f"{_MAX_CONSEC_FAULTS} stalls in a row - stopping CREEP_TICKS refinement.")
                    break
                if m['fault'] == 0 and m['overshoot'] == 0:
                    best_creep_ticks = ct
                    best_m = m
                    break
            else:
                _log(dmesg, "Overshoot persists; also consider lowering MAX.")
                best_creep_ticks = servo.creep_ticks
            servo.set_creep_ticks(best_creep_ticks)

        # Measurements done - park the servo before the interactive prompts. The
        # deferred post-peel stop is due POST_PEEL_MS after the last feed, but the
        # dwell (100ms) is shorter and nothing pumps update() past this point, so
        # without an explicit stop the peel motor would run through the prompts.
        servo.stop()

        _log(dmesg, "=== Recommendation ===")
        _log(dmesg, f"CREEP={best_creep}, CREEP_TICKS={best_creep_ticks} " +
                    f"(err std={best_m['std']:.1f}, bias={best_m['mean']:.1f}, " +
                    f"overshoot={best_m['overshoot']}/{best_m['n']})")
        _explain_choice(dmesg, results, best_creep, best_m, ticks_per_mm)
        if best_creep_ticks != orig['creep_ticks']:
            _log(dmesg, f"  CREEP_TICKS lengthened {orig['creep_ticks']} -> {best_creep_ticks} " +
                        "to absorb momentum and eliminate overshoot.")
        _geometry_notes(servo, dmesg, distance, pitch_mm)

        # --- Persist? ----------------------------------------------------
        try:
            ans = _input("Save to sysconfig and apply? (Y/n): ").lower()
        except Exception:
            ans = 'y'  # headless: persist by default

        if ans in ('', 'y', 'yes'):
            sysconfig.set('SERVO.CREEP', best_creep)
            sysconfig.set('SERVO.CREEP_TICKS', best_creep_ticks)
            sysconfig.set('SERVO.TOLERANCE', servo.tolerance)
            sysconfig.save()
            # Live servo already holds best_creep / best_creep_ticks / tolerance.
            _log(dmesg, "Saved and applied.")
        else:
            servo.creep_output = orig['creep']
            servo.set_creep_ticks(orig['creep_ticks'])
            servo.tolerance = orig['tolerance']
            _log(dmesg, "Discarded; servo restored to previous values.")

        # --- Unloading aid ------------------------------------------------
        _offer_rewind(servo, dmesg, start_pos, ticks_per_mm)

    except Exception as e:
        _log(dmesg, f"ERROR during tuning: {e}")
        servo.creep_output = orig['creep']
        servo.set_creep_ticks(orig['creep_ticks'])
        servo.tolerance = orig['tolerance']
    finally:
        servo.peel_enable(orig['peel'])
        servo.disable()
        _log(dmesg, "Auto-tune finished.")
