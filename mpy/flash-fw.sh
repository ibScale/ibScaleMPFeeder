#!/bin/bash
# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>
#
# flash-fw.sh - Flash the built firmware to the board over DFU.
#
# Put the board in DFU mode first:
#   - At the REPL: machine.bootloader()
#   - Or hold BOOT and power-cycle the board.
#
# Run from the mpy/ directory:
#   ./flash-fw.sh [path-to-micropython-source]

BOARD=ibScaleMPFeeder
MPY_DIR="${1:-../../micropython}"

if ! command -v dfu-util &>/dev/null; then
  echo "dfu-util not found. Install it first (see README Prerequisites)."
  exit 1
fi

STM32_DIR="$(cd "$MPY_DIR/ports/stm32" 2>/dev/null && pwd)"
if [[ -z "$STM32_DIR" ]]; then
  echo "MicroPython source not found at '$MPY_DIR'."
  echo "Usage: $0 [path-to-micropython]"
  exit 1
fi

BUILD_DIR="$STM32_DIR/build-$BOARD"

# Segment load addresses - must match the linker layout (stm32f411_ibscale.ld):
# ISR vector table at the start of flash, main text after the 48K filesystem.
TEXT0_ADDR=0x08000000
TEXT1_ADDR=0x08010000

fw0="$BUILD_DIR/firmware0.bin"
fw1="$BUILD_DIR/firmware1.bin"
fw_dfu="$BUILD_DIR/firmware.dfu"

if [[ ! -f "$fw_dfu" ]]; then
  echo "Firmware not found: $fw_dfu"
  echo "Build it first with: ./compile-fw.sh"
  exit 1
fi

read -p "Flash build-$BOARD firmware to device in DFU mode? (y/N): " response
if [[ ! "$response" =~ ^[Yy]$ ]]; then
  exit 0
fi

if [[ -f "$fw0" && -f "$fw1" ]]; then
  # Flash the raw segments so the final download can carry the DfuSe ':leave'
  # modifier - the ST ROM bootloader doesn't support DFU detach (the
  # "dfu-util: can't detach" you'd otherwise see), but ':leave' makes it jump
  # straight into the new firmware. No power cycle needed.
  dfu-util -a 0 -d 0483:df11 -s $TEXT0_ADDR -D "$fw0" &&
  dfu-util -a 0 -d 0483:df11 -s $TEXT1_ADDR:leave -D "$fw1" &&
  echo "Flashed - device is rebooting into the new firmware."
else
  # Fallback: whole-image DfuSe file; the bootloader can't self-restart from
  # this path, so a manual reset/power cycle is required afterwards.
  dfu-util -a 0 -d 0483:df11 -D "$fw_dfu" -R
  echo "Flashed - power cycle or reset the board to start the new firmware."
fi
