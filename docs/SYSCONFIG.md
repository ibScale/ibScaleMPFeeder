# SysConfig Reference

[← Back to README](../README.md)

All settings live in `sysconfig.json` on the device filesystem and are read at boot. The compiled-in defaults are in [`mpy/lib/defaults.py`](../mpy/lib/defaults.py) — any key missing from the JSON is filled in automatically on the next boot.

Settings can be changed three ways:

1. **Console SysConfig menu** (ESC × 3 → SysConfig) — edit any key live and save without leaving the feeder running
2. **REPL** — use dot-notation via the Python API, then save:
   ```python
   SYSCONFIG.get('SYSTEM.DEBUG')      # read
   SYSCONFIG.set('SERVO.MAX', 75)     # write
   SYSCONFIG.save()                   # persist to flash
   ```
3. **Direct file edit** — drop to REPL from the console (R), which mounts the `MPFEEDER` USB volume on the host. Then either edit `sysconfig.json` directly in any text editor or copy your own pre-made `sysconfig.json` to the device with mpremote.

## Key settings

### SYSTEM

| Key | Default | Notes |
|---|---|---|
| `SYSTEM.TICKS_010MM` | `22.546` | Encoder ticks per 0.10 mm — derived from hardware design; set manually if your encoder resolution differs |
| `SYSTEM.SLOT_OVERRIDE` | `False` | When `True`, boot skips reading the EEPROM entirely and advertises whatever `SYSTEM.SLOT_ID` already holds — for boards with no EEPROM populated, or to pin a fixed slot regardless of what's programmed onto the chip |
| `SYSTEM.WATCHDOG_S` | `0` | Hardware watchdog timeout in seconds; `0` = disabled. Max 30 seconds. Once armed, runs until reset |
| `SYSTEM.TEMP_MAX_C` | `70` | MCU temperature (°C) at/above which the LED turns solid red (fault); `0` disables the check |
| `SYSTEM.DEBUG` | `False` | Verbose logging — generates significant log output |

### APP

| Key | Default | Notes |
|---|---|---|
| `APP.JOG_MM` | `2` | Distance in mm a UP/DOWN short click jogs (2mm matches the Photon reference firmware) |
| `APP.SLOT_PROFILE` | `'normal'` | Speed profile for button jogs: `gentle`, `normal`, or `fast` |

### ADC

| Key | Default | Notes |
|---|---|---|
| `ADC.VDC_MIN` / `VDC_MAX` | `20.0` / `28.0` | Valid range (V) for the 24V input rail (`VMONVDC`, ADC1_IN8 / connector Pin 18); outside this range is a fault |
| `ADC.VSYS_MIN` / `VSYS_MAX` | `9.0` / `11.0` | Valid range (V) for the regulated 10V buck rail (`VMONSYS`, ADC1_IN9 / connector Pin 19); outside this range is a fault |

### LED

| Key | Default | Notes |
|---|---|---|
| `LED.INVERT` | `True` | Common-cathode (`True`) vs. common-anode (`False`) polarity. Set by the console's LED wiring calibration, not meant to be hand-guessed |
| `LED.CHANNEL_COLORS` | `['R', 'G', 'B']` | Which physical PWM channel (`RED_CH`/`GREEN_CH`/`BLUE_CH`, in that order) actually emits which color. Only needs changing from the identity order if a board's LED die order doesn't match the pin names — set by LED wiring calibration |

### BUTTONS

| Key | Default | Notes |
|---|---|---|
| `BUTTONS.UP_INVERT` / `DOWN_INVERT` | `True` / `True` | Set if the corresponding button is active-low (pressed = pin reads low) — the default pull-up wiring |

### SERVO

| Key | Default | Notes |
|---|---|---|
| `SERVO.MAX` | `80` | Peak motor drive (0–100). Lower if parts overshoot consistently |
| `SERVO.CREEP` | `15` | Terminal approach speed. Lower = more repeatable stop, too low = stall |
| `SERVO.KICK` | `60` | Breakaway duty floor while an approach hasn't moved yet, to overcome stiction. Ends after `KICK_TICKS` of travel or `KICK_MS`, whichever comes first. `0` disables |
| `SERVO.TOLERANCE` | `15` | In-tolerance window in encoder ticks to confirm a stop |
| `SERVO.STALL_MS` | `300` | Fault if no encoder progress for this long while driving (jam detection) |
| `SERVO.PEEL_ENABLE` | `True` | Run the peel motor alongside the drive motor during moves |
| `SERVO.PEEL_SPEED` | `100` | Peel motor speed (0–100) while a drive move is active |
| `SERVO.POST_PEEL_MS` | `200` | How long the peel motor keeps running after the drive move stops, so it clears the tape before braking. Non-blocking — serviced from the main 20ms loop, not the real-time move burst |

The `SERVO.PROFILES` block defines `gentle`, `normal`, and `fast` as scale factors on `SERVO.MAX` and `SERVO.ACCEL_TICKS`. The creep tail (`SERVO.CREEP` / `SERVO.CREEP_TICKS`) is shared across all profiles so stop accuracy is the same regardless of profile — only peak speed and acceleration change.

See [Software Servo](SERVO.md) for how these settings actually shape a move.

### RS485

| Key | Default | Notes |
|---|---|---|
| `RS485.BAUDRATE` | `57600` | Must match the LumenPNP host setting |

See [Photon Protocol / RS485 Transport](PHOTON.md) for the transport this feeds.
