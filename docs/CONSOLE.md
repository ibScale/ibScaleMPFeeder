# Serial Console

[← Back to README](../README.md)

During normal operation **Ctrl+C is disabled** so the application owns the USB VCP port cleanly. Enter the console by pressing **ESC three times within one second**. The console times out after 5 minutes of inactivity and returns to normal operation. The console is blocking while active and prevents normal feeder operation. When inactive a general status log output is displayed on the console for monitoring.

During boot only (before the app starts), **Ctrl+C** also opens the console.

## Menu options

- **Run calibration** — an interactive wizard that asks which tests to run then executes them in sequence: drive PWM-minimum + coasting-distance measurement with motor/encoder direction confirmation, peel motor direction confirmation, a guided button test (prompts for a single click, double click, then long press on each of UP and DOWN, confirming each gesture is detected), and LED calibration (drives the LED off/on channel-by-channel and asks what you see to determine common-anode/cathode polarity and which physical channel emits which color — see `LED.INVERT`/`LED.CHANNEL_COLORS` in the [SysConfig Reference](SYSCONFIG.md) — then cycles through the palette at 500ms/color to confirm)
- **Run servo auto-tune** — tune servo stop accuracy against tape loaded in the feeder (see [Auto-tune](SERVO.md#auto-tune))
- **SysConfig** — view or edit any configuration key value (see the [SysConfig Reference](SYSCONFIG.md))
- **Show dmesg log** — display the in-memory log and any rotated log files
- **Status** — show current servo state, voltages, and memory
- **Program Feeder Floor** — the console equivalent of a host sending Photon's `PROGRAM_FEEDER_FLOOR` command (see [Photon Protocol](PHOTON.md)): reads the current Slot ID from the EEPROM (falling back to the cached `SYSTEM.SLOT_ID` in sysconfig if there's no EEPROM or the read fails), then optionally programs a new one — asks for the new Slot ID (1-254), confirms before writing, and persists it to both the EEPROM (verified write) and sysconfig. Useful ahead of RS485 host access, or on `SLOT_OVERRIDE` boards with no EEPROM populated (sysconfig-only in that case). Takes effect on the RS485 bus after a reboot.
- **Drop to REPL** — halt the application and drop to the MicroPython REPL. USB re-enumerates as VCP+MSC: **your serial terminal may disconnect** and the `MPFEEDER` volume will mount on the host. Reconnect your terminal to reach the REPL prompt. The feeder is not running while in this mode — Photon commands will not be serviced. Run `machine.soft_reset()` to reset the board and return to normal operation.
- **Reboot (soft)** — `machine.soft_reset()`
- **Hard reset** — `machine.reset()`
- **Factory defaults** — wipe `/flash` (config, logs, dev overrides) and reboot to firmware defaults; requires typing `RESET` to confirm.
- **Enter DFU** — `machine.bootloader()`, for firmware updates without a physical BOOT-button power cycle
- **Exit console** — return to normal operation immediately, without waiting for the idle timeout

Any unhandled error inside the console menu is caught, logged to dmesg, and printed with a full traceback rather than crashing the console — it returns you to normal operation instead.

The auto-tuner tunes servo stop repeatability by measuring real feed cycles against a tape loaded in the feeder, and the software servo itself uses a feedforward velocity profile rather than PID — see [Software Servo](SERVO.md) for the full write-up (auto-tune workflow, how to read its output, and the motion-profile math).

## REPL shortcuts

The firmware also exposes a few shortcut functions at the REPL for development:

```python
dfu()        # Enter DFU bootloader
reboot()     # Soft reboot
calibrate()  # Run calibration (includes the guided button test)
profiler()   # Run the timing profiler
```
