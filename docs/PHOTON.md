# Photon Protocol / RS485 Transport

[← Back to README](../README.md)

This firmware implements the Opulo/LumenPNP **Photon** RS485 protocol, based on the [Opulo feeder source code](https://github.com/photonfirmware/photon) and the [Photon protocol documentation](https://docs.opulo.io/misc/photon/), so the board answers a stock LumenPNP host exactly like an original Photon feeder.

The implementation is split into three layers, deliberately kept independent so any one of them can be swapped without touching the others:

| Layer | File | Responsibility |
|---|---|---|
| Transport | `mpy/lib/hardware/rs485.py` | Half-duplex RS485 byte transport: IRQ-driven RX chunk queue (`read_chunk()`), DE-pin-gated blocking TX (`send_packet()`). Knows nothing about packet formats, addressing, or CRCs |
| Packetizer | `mpy/lib/application/packetizer.py` | Packet framing: `validate_packet()`, `parse_packet()`, `format_packet()`, plus the command/response byte constants |
| Protocol | `mpy/lib/application/photon.py` | The Photon state machine — dispatches each validated command to a handler, drives the servo, and tracks feeder identity/initialization state |

## Transport

RS485 hardware: **THVD1400DR**, 500 Kbps, IEC-61000-4-2/4 compliant transceiver, driven over `RS485.UART_ID` with a DE pin toggled around each transmit. RX is interrupt-driven (`UART.IRQ_RXIDLE`): the UART frames bus traffic into bursts, one chunk per transmission, queued into a bounded ring buffer so a slow/absent consumer (manual mode, or a protocol layer blocked in a long move) can't grow the heap — the oldest burst is dropped on overflow so the freshest traffic survives.

Relevant settings live under `RS485.*` in sysconfig — see the [SysConfig Reference](SYSCONFIG.md#rs485). `RS485.BAUDRATE` (default `57600`) must match the LumenPNP Host. Framing is 8N1 on both sides: the reference firmware's `Serial.begin(baud)` call omits an explicit frame-format argument, so it falls back to the Arduino/STM32duino default of 8 data bits, no parity, 1 stop bit.

## Protocol behavior

- **Move model**: `MOVE_FEED_FORWARD`/`MOVE_FEED_BACKWARD` reply immediately with `OK` + expected time (ms), then run the feed as a real-time burst (`servo.run_move()`) to completion. The feeder is briefly unresponsive during the feed. `MOVE_FEED_STATUS` returns the stored result of the last move.
- **Addressing**: unicast commands require the feeder to already be initialized (`INITIALIZE_FEEDER` with a matching 12-byte UUID); broadcast commands (`GET_FEEDER_ADDRESS`, `IDENTIFY_FEEDER`, `PROGRAM_FEEDER_FLOOR`, `UNINITIALIZED_FEEDERS_RESPOND`) work regardless, gated on a UUID match so other feeders on the bus stay silent.
- **Floor programming**: `PROGRAM_FEEDER_FLOOR` persists the new slot address to the EEPROM (verified write) and to `sysconfig.json`, then updates the live RS485 address filter immediately — no reboot needed.
- **Console/errors**: an unhandled exception inside a command handler is logged and does not crash the protocol loop; the next tick continues normally.

## LED Status

The Photon state machine drives the status LED directly — colors are **policy, not code**: firmware always sets the LED by status name (`LED.state('fault')`, `state('ready')`, …) and the name→color mapping lives in one place, `LED.STATES` in `defaults.py`. Re-theme any state by editing that map; no code changes needed.

| Color | Meaning |
|---|---|
| Purple (solid) | Boot default, before the Photon state machine takes over |
| Yellow (solid) | Photon running, feeder not yet initialized by the host |
| Green (solid) | Feeder initialized and running normally |
| *(current color) blinking* | Serial console is active - blinks whatever color is currently set, whatever that may be |
| Cyan (solid) | A move is in progress (returns to the prior color once it stops) |
| Blue (blinking, ~5s) | Identify command received (returns to the prior color after ~5s) |
| Red (solid) | Fault - motor stall/timeout, overtemperature (`SYSTEM.TEMP_MAX_C`), voltage out of range (`ADC.VDC_MIN`/`MAX`, `ADC.VSYS_MIN`/`MAX`), or bootstrap failure |

`led.py`'s interface is deliberately just two verbs: `color(name)` sets the solid/resting color, and `blink(interval_ms)` blinks whatever color is currently set (`blink(0)` stops). `color()` takes either a named color (the 16 standard ANSI/VGA colors — see `COLORS` in `led.py`) or a hex code (`'#RGB'` / `'#RRGGBB'`, case-insensitive, e.g. `'#0f0'`/`'#00FF00'` for green). The boot-default purple (`'#800080'`) isn't one of the 16 named colors, so it's set directly by hex code.

Callers (Photon, the fault monitor in `app.py`) never save or restore state in `led.py` itself — they just remember `led.current_color` before setting a temporary color, then call `color()` again with that name when done. This works because every override is bracketed within one well-defined stretch of code: a blocking move, a fault condition, a timed identify flash.

The one edge case this doesn't fully resolve: two independent, overlapping, non-blocking overrides — e.g. an identify flash still running when a fault clears (or vice versa) — where whichever finishes second can restore a stale color. Given how rare and low-stakes that overlap is, this is an accepted trade-off for keeping the LED module simple.

## Swapping a layer

Each layer's contract (from [Architecture & Component Contracts](ARCHITECTURE.md#architecture--component-contracts)):

| Seam | Contract a replacement must provide |
|------|-------------------------------------|
| **Transport** (`hardware/rs485.py`) | `read_chunk() -> bytes\|None` (one bus burst, oldest first), `send_packet(bytes) -> bool` |
| **Protocol** (`application/photon.py` + `packetizer.py`) | anything driving the transport contract with an `update()` called each app tick. The transport is protocol-agnostic: validation, addressing, and CRC live entirely in the protocol layer, so a different protocol (e.g. Modbus RTU) is a new module pair + the `app.py` hookup |
| **Packetizer** (`application/packetizer.py`) | `validate_packet(raw, addr, logger, debug) -> bytes\|None`, `parse_packet(bytes) -> dict`, `format_packet(...) -> bytes`, command/response constants |
