# Software Servo

[← Back to README](../README.md)

`mpy/lib/system/servo.py` positions the feeder by **where the motor stops**, not with a high-rate position-error loop. A feedforward velocity profile (distance → speed) drives the move, the last stretch holds a slow constant `CREEP` speed, and the drive brakes the instant the encoder crosses the target. Final accuracy comes from a repeatable slow stop, not tuned PID gains. The commanded duty each tick is a pure function of the current (remaining, traveled) ticks, recomputed from scratch on every call.

The final approach is always **forward**, so gear/sprocket backlash is taken up the same way on every move. A reverse request first backs off past the target, then approaches forward. A stall/timeout watchdog turns a jam into a reported fault instead of driving indefinitely.

The state machine diagram and the exact velocity-profile math (accel/decel ramps, the breakaway-kick floor, backlash-takeup arithmetic, settle debouncing, fault detection, and the cumulative-grid `feed()`/`reseed()` model) live in the extensive header comment in `mpy/lib/system/servo.py` — that's the canonical source for the math. This doc covers the operational side: how to tune it.

Relevant settings live under `SERVO.*` in sysconfig — see the [SysConfig Reference](SYSCONFIG.md#servo) for the full list and defaults.

## Auto-tune

The auto-tuner tunes the two knobs that govern stop repeatability — `SERVO.CREEP` (terminal approach speed) and `SERVO.CREEP_TICKS` (slow-tail length) — by measuring real feed cycles against a tape loaded in the feeder:

1. It prompts for the tape pitch (default 4 mm) and uses that as the trial distance, so every trial is exactly what a production feed for this tape will be. It also asks whether to run the **peel motor** during the run. It's recommended to run the auto-tuner with a used section of tape or tape with the film left on. By default we assume film is already peeled back and default to Yes. It also prompts for the servo **tolerance** in ticks — how close a stop must land to count as "reached" rather than overshoot — defaulting to the live `SERVO.TOLERANCE` from sysconfig; a blank answer keeps that default.
2. Each trial runs the production code path: a `feed()` with cumulative grid targeting and the slot's speed profile, executed to completion as a `run_move()` real-time burst — then a **100 ms at-rest dwell** simulating the pick phase of a real SMD cycle (feed → stop → pick → feed). During the dwell `servo.update()` is pumped at the main-loop rate, so post-move housekeeping behaves exactly as in normal operation.
3. It sweeps `CREEP` from fast to slow (6 feed/stop cycles per candidate), scores each batch on repeatability (std dev), bias, overshoot, and faults, and picks the slowest reliable speed with no overshoot. If overshoot persists, it lengthens `CREEP_TICKS` (1.5/2.0/2.5×) until it clears.
4. It prints a recommendation with geometry notes for the pitch (e.g., a warning if the creep tail doesn't fit inside a short pitch), then asks before saving to sysconfig — declining restores the previous values. It will also ask if you want to rewind the tape back to it's starting position.

**Reading the output.** Each sweep step prints one line per candidate, e.g.:

```
CREEP=20: err mean=-9.2 std=0.4 [-10..-9], overshoot=0/6, t=347ms
```

All position numbers are **encoder ticks**; with the default `SYSTEM.TICKS_010MM = 22.546` one tick ≈ 4.4 µm (≈ 225 ticks per mm), so the example above stopped 0.04 mm short on average with ±2 µm of scatter. With the N20 gear motor used on the LumenPNP Feeder design you have 32 ticks per motor revolution with the hardware quadrature encoding.

| Field | Meaning |
|-------|---------|
| `err mean` | Average stop error of the batch (negative = stopped short of target). Consistent bias is mostly harmless: feeds target the cumulative grid, so each feed automatically makes up the previous one's shortfall — the *average pocket spacing* stays exact |
| `std` | Repeatability (standard deviation of stop error) — **the number that matters most**; it's the part of the error that grid targeting can't cancel |
| `[min..max]` | Worst-case spread of stop errors in the batch |
| `overshoot=n/N` | Moves that ran *past* the target by more than `SERVO.TOLERANCE`. Penalized heavily: feeding is forward-only, so an overshoot can't be backed out — the grid absorbs it into the next feed instead |
| `t` | Average move time — the throughput cost of a slower CREEP |
| `FAULTED` | The batch hit a stall/timeout; that CREEP value is unusable |

Candidates are scored on `std`, then bias, with a heavy overshoot penalty; ties go to the **slower** CREEP (gentler on parts). The final recommendation repeats the winning batch's numbers as `(err std=…, bias=…, overshoot=…)`, then explains itself in plain language: why that CREEP won (its score vs. the runner-up, and any candidates excluded for faults), repeatability and bias converted to µm with a note on which of the two actually matters, and the per-feed time.

A stall at any `CREEP` disqualifies that speed **and every slower one tested afterward** in the same sweep, even if a later batch happens to come back clean — a slower creep only has less momentum to work with, so it's assumed at least as stall-prone rather than trusting a small sample that got lucky.

Movement is **strictly forward** throughout: tape can't be rewound through the mechanism, so the run consumes real tape. A worst-case travel estimate is logged before the sweep starts — make sure at least that much tape is loaded. When finished, the tuner reports the total tape consumed and offers to **rewind to the starting position** (a reverse move with stall detection active), which makes unloading easy when the tape is still attached to its reel.

Run it from the console (ESC × 3 → **Run servo auto-tune**) or at the REPL with `profiler()`.
