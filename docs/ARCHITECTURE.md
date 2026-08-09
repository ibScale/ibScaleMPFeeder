# Architecture

[← Back to README](../README.md)

## Directory Structure

```
mpy/
├── flash/
│   ├── boot.py             # Sets USB to VCP-only at startup (MSC enabled on REPL drop)
│   ├── main.py             # Setup the environment and hardware
│   └── app.py              # Main app control loop
├── lib/
│   ├── application/
│   │   ├── packetizer.py   # RS485 packet framing
│   │   └── photon.py       # Photon protocol state machine
│   ├── hardware/
│   │   ├── adc.py          # Voltage monitors + MCU temperature
│   │   ├── buttons.py      # Debounced button FSM (click/double/hold)
│   │   ├── drives.py       # H-bridge PWM driver (drive + peel motors)
│   │   ├── eeprom.py       # EEPROM abstraction layer
│   │   ├── eeprom_ds28e07.py  # Maxim DS28E07 1-Wire driver
│   │   ├── eeprom_at21cs01.py # Atmel AT21CS01 1-Wire driver
│   │   ├── encoder.py      # HW quadrature encoder
│   │   ├── led.py          # RGB LED
│   │   └── rs485.py        # IRQ-driven RS485 ring buffer
│   ├── system/
│   │   ├── bootstrap.py    # Hardware init and driver wiring
│   │   ├── console.py      # USB VCP serial console (ESC × 3 entry)
│   │   ├── dmesg.py        # In-memory + rotating file log
│   │   ├── gcutil.py       # Shared gc.collect() wrapper
│   │   ├── peel.py         # Peel motor: forward/reverse/stop
│   │   ├── servo.py        # Profile-based software servo
│   │   ├── sysconfig.py    # JSON config with atomic save
│   │   └── watchdog.py     # Hardware IWDG wrapper
│   ├── util/
│   │   ├── calibrate.py    # Calibration wizard
│   │   ├── misc.py         # Memory/VFS helpers, dev test launchers
│   │   └── profiler.py     # SMD Tape profiler
│   └── defaults.py         # Default sysconfig values
├── manifest.py             # Frozen module list
├── mpconfigboard.h         # Board hardware defines
├── mpconfigboard.mk        # Build configuration and linker script selection
├── stm32f411_ibscale.ld    # Custom linker script (48K LFS + 464K firmware)
└── pins.csv                # Board pin name aliases
pcb/
├── ibScaleMPFeeder.kicad_pro   # KiCad project
├── ibScaleMPFeeder.kicad_sch   # Schematic
└── ibScaleMPFeeder.kicad_pcb   # PCB layout
docs/
├── ARCHITECTURE.md         # This file
├── INSTALL.md              # Toolchain install, build, flashing, and first-boot calibration
├── CONSOLE.md              # Serial console menu reference + REPL shortcuts
├── SYSCONFIG.md            # Full sysconfig key/default/notes reference
├── SERVO.md                # Software servo model + auto-tune workflow
└── PHOTON.md               # Photon protocol, packetizer, RS485 transport
README.md
```

## Architecture & Component Contracts

The firmware is deliberately modular: components never construct each other. **`main.py` is the single composition root** — it builds every hardware/system object and registers it in the `app_passthrough` dict, which acts as the service registry for the application layer, console, and dev tools. To swap an implementation, you change that section of `main.py` (or the config that drives it); nothing else should need editing. Because a file on `/flash` shadows its frozen twin, any single module can also be replaced on a running feeder without recompiling firmware although some modules are bigger then the 48K available.

All interfaces are duck-typed; the tables below are the contracts a replacement must honor.

### The `app_passthrough` registry

| Key | Required? | Provided by | Consumed by |
|-----|-----------|-------------|-------------|
| `DMESG` | yes | main.py | everyone (logging) |
| `SYSCONFIG` | yes | main.py | everyone (config) |
| `LED` | yes | bootstrap | app, Photon, console, main |
| `DRIVES` | yes | bootstrap | Servo (via injection), calibrate |
| `ENCODER` | yes | bootstrap | Servo (via injection), app, calibrate |
| `SERVO` | yes | bootstrap | app, Photon, console, profiler |
| `RS485` | yes | bootstrap | app (handed to Photon as the transport) |
| `BTNUP` / `BTNDOWN` | optional | bootstrap | app, calibrate |
| `ADC` | optional | bootstrap | app, console |
| `EEPROM` | optional | bootstrap | bootstrap (slot ID), Photon (floor programming) |

Optional keys are accessed with `.get()` and every consumer degrades gracefully when they're absent.

### Swappable seams

| Seam | Contract a replacement must provide | Where it's wired |
|------|-------------------------------------|------------------|
| **Transport** (`hardware/rs485.py`) | `read_chunk() -> bytes\|None` (one bus burst, oldest first), `send_packet(bytes) -> bool` | bootstrap; consumed by the protocol layer |
| **Protocol** (`application/photon.py` + `packetizer.py`) | anything driving the transport contract with an `update()` called each app tick. The transport is protocol-agnostic: validation, addressing, and CRC live entirely in the protocol layer, so a different protocol (e.g. Modbus RTU) is a new module pair + the app.py hookup | app.py |
| **Packetizer** (`application/packetizer.py`) | `validate_packet(raw, addr, logger, debug) -> bytes\|None`, `parse_packet(bytes) -> dict`, `format_packet(...) -> bytes`, command/response constants | imported only by its protocol module |
| **EEPROM driver** (`hardware/eeprom_*.py`) | `read_memory(addr, len) -> bytes\|None`, `write_memory(addr, data) -> bool` (verified) | `eeprom.py` factory, selected by `SYSTEM.EEPROM_DRIVER` |
| **Peel mechanism** (`system/peel.py`) | `forward()`, `reverse()`, `stop()`, `is_idle()` | injected into `Servo(peel=...)` in bootstrap |
| **Status indicator** (`hardware/led.py`) | `state(name)` for the status names in `LED.STATES` (`boot`/`waiting`/`ready`/`feeding`/`identify`/`fault`/`stopped`), plus `color()`, `blink()`, `poll()`, `current_color`. Colors are policy, held in one map — re-theme via config, never in code | bootstrap; policy in `defaults.py` `LED.STATES` |
| **Application** (`flash/app.py`) | module with `run_app(app_passthrough)`; selected by `SYSTEM.APP` | main.py |
| **Servo** (`system/servo.py`) | consumers use `feed()`, `set_target()`, `run_move()`, `update()`, `stop()`, `reseed()`, `result`/`result_name`, `commanded_position`, `is_busy`, `enable()/disable()`, `peel_enable()` | bootstrap |

Rules that keep this working: **only bootstrap/main construct objects** — everything else receives instances; components talk to *objects they were given*, never import a sibling's module to reach hardware; and platform-specific code (pyb/stm32 registers) stays inside `hardware/`.
