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

firmware="$STM32_DIR/build-$BOARD/firmware.dfu"

if [[ ! -f "$firmware" ]]; then
  echo "Firmware not found: $firmware"
  echo "Build it first with: ./compile-fw.sh"
  exit 1
fi

read -p "Flash $firmware to device in DFU mode? (y/N): " response
if [[ "$response" =~ ^[Yy]$ ]]; then
  dfu-util -a 0 -D "$firmware" -R
fi
