# Building & Flashing

[← Back to README](../README.md)

## Building the Firmware

### Prerequisites

- MicroPython 1.28.0+ source tree
- ARM embedded toolchain: `arm-none-eabi-gcc`, `arm-none-eabi-newlib`, `arm-none-eabi-binutils`
- `dfu-util` (for flashing)
- `make`, `python3`

**Arch Linux**
```bash
sudo pacman -S arm-none-eabi-gcc arm-none-eabi-newlib arm-none-eabi-binutils dfu-util
```

**Debian / Ubuntu**
```bash
sudo apt install gcc-arm-none-eabi binutils-arm-none-eabi libnewlib-arm-none-eabi dfu-util make python3
```

**Red Hat / Fedora**
```bash
sudo dnf install arm-none-eabi-gcc arm-none-eabi-binutils arm-none-eabi-newlib dfu-util make python3
```
**macOS**

Install [Homebrew](https://brew.sh) if not already present, then:
```bash
brew install --cask gcc-arm-embedded
brew install dfu-util
```

`gcc-arm-embedded` installs the official Arm toolchain release (includes gcc, binutils, and newlib). If you already have a toolchain installed via a different method, ensure `arm-none-eabi-gcc` is on your `PATH` before building.

### Build

Clone this repo alongside the MicroPython 1.28.0 source tree, then run the build script from the `mpy/` directory:

```bash
git clone https://github.com/micropython/micropython.git
git clone https://github.com/ibscale/ibScaleMPFeeder.git
cd ibScaleMPFeeder/mpy
./compile-fw.sh [opt-path-to-micropython]
```

The script defaults to `../../micropython` if no path is given, which works when both repos are siblings under the same parent directory as in the above example. It will:
1. Optionally clean the previous build output
2. Build `mpy-cross` (required for frozen modules)
3. Update MicroPython submodules for the STM32 port
4. Build the firmware

The output is `micropython/ports/stm32/build-ibScaleMPFeeder/firmware.dfu`.

To build manually instead:
```bash
cd micropython
make -C mpy-cross
cd ports/stm32
make BOARD=ibScaleMPFeeder BOARD_DIR=/path/to/ibScaleMPFeeder/mpy
```

### External SPI Flash (dev builds)

The board has an optional external SPI NOR flash footprint (`FLASHNSS`/`FLASHSCK`/`FLASHMISO`/`FLASHMOSI` on SPI1, `pins.csv`), off by default — the standard build uses the internal 48K filesystem exactly as described elsewhere in this doc and the main README. When populated and enabled at build time, `/flash` moves to that external chip instead, which is much bigger than the internal 48K. The point isn't capacity for its own sake: it's headroom for **dev work without recompiling** — a `/flash` copy of a module shadows its frozen twin (see [Architecture](ARCHITECTURE.md)), but the internal filesystem is too small to hold a shadow copy of some of the larger modules. The external chip removes that ceiling.

This is a **build-time** toggle (MicroPython's storage backend is compiled in, not something `sysconfig.json` can switch), opted into with `--ext_flash <size-mb>` — off (assume no chip present) unless given:

```bash
./compile-fw.sh --ext_flash 4
```
or manually, via the underlying `SPI_FLASH_SIZE_MB` make variable — same mechanism as the stock WeAct Black Pill reference board this port is based on:
```bash
make BOARD=ibScaleMPFeeder BOARD_DIR=/path/to/ibScaleMPFeeder/mpy SPI_FLASH_SIZE_MB=4
```

This changes the build output directory to `build-ibScaleMPFeeder_FLASH_4M` (suffixed with the chosen size). Pass the **same** `--ext_flash <size-mb>` to `flash-fw.sh` so it looks in the right place:
```bash
./flash-fw.sh --ext_flash 4
```

### Updating MicroPython

To move to a newer MicroPython source snapshot, update the checkout (and its own submodules, e.g. `lib/mbedtls`, `lib/lwip`, `lib/berkeley-db-1.xx`) before rebuilding:

```bash
cd micropython
git pull
git submodule update --init --recursive
```

Then rebuild with `./compile-fw.sh` as usual. It always rebuilds `mpy-cross` first (the frozen-module bytecode format is version-locked to it) and re-runs the STM32 port's own `make submodules` target, so a stale `mpy-cross` or submodule state can't silently produce a mismatched firmware image.

## Flashing

Put the board into DFU mode first: Enter DFU flashing from the console menu, call `machine.bootloader()` at the MicroPython REPL, or hold the BOOT button while applying power.

```bash
cd ibScaleMPFeeder/mpy
./flash-fw.sh [opt-path-to-micropython]
```

The script locates the firmware built by `compile-fw.sh` (pass the same `--ext_flash <size-mb>` used at build time, if any, so it looks in the right build output directory — see above), confirms before writing, optionally offers to mass-erase the chip first (see below), then flashes the two raw segments with `dfu-util`, tagging the final download with the DfuSe `:leave` modifier so the board **reboots straight into the new firmware** — no power cycle needed. (The ST ROM bootloader doesn't support DFU detach, which is why flashing the whole `.dfu` file with `-R` leaves the board parked in DFU mode; the script only falls back to that if the segment binaries are missing.) Pass the same MicroPython path used during the build if it is not at the default location.

When flashing the raw segments, the script also asks whether to erase the chip first (`dfu-util`'s `mass-erase:force` modifier). This wipes the **whole chip**, including the `/flash` filesystem (`sysconfig.json`, logs, dev overrides) — not just the firmware — so answer `y` only when you want a clean-slate board; the default `N` leaves existing config/logs untouched, matching a normal firmware update. Not offered on the whole-image `.dfu` fallback path, since `dfu-util`'s mass-erase modifier only applies to raw segment downloads.

## First Boot (Factory Default)

On the first boot the firmware writes `sysconfig.json` to `/flash` from the compiled-in defaults.py if no previous configuration is found. No other setup is required to get the feeder running. With new or factory-defaulted feeders it is necessary to run the calibration process. This calibration sets motor direction, speeds, LED color mapping, and button functionality.

To calibrate the feeder:

1. Connect to the USB serial port with any terminal or `mpremote` (USB serial doesn't use baud rates, but 115200 if it's required is fine)
2. Once the app starts, press **ESC three times within one second** to bring up the console
3. Select **Calibrate** from the menu and follow the prompts
4. The calibration result is saved to `sysconfig.json` automatically

Alternatively, a known good sysconfig can be copied to the feeder to avoid the calibration process on bulk deployments.
