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
#   ./flash-fw.sh [path-to-micropython-source] [--ext_flash <size-mb>]
#
# --ext_flash must match whatever was passed to compile-fw.sh for this build (its
# output lives in a differently-suffixed build dir); omit it for the standard
# no-external-flash build. See docs/INSTALL.md.

BOARD=ibScaleMPFeeder

MPY_DIR=""
SPI_FLASH_SIZE_MB=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ext_flash)
      SPI_FLASH_SIZE_MB="$2"
      shift 2
      ;;
    *)
      MPY_DIR="$1"
      shift
      ;;
  esac
done
MPY_DIR="${MPY_DIR:-../../micropython}"

if ! command -v dfu-util &>/dev/null; then
  echo "dfu-util not found. Install it first (see README Prerequisites)."
  exit 1
fi

STM32_DIR="$(cd "$MPY_DIR/ports/stm32" 2>/dev/null && pwd)"
if [[ -z "$STM32_DIR" ]]; then
  echo "MicroPython source not found at '$MPY_DIR'."
  echo "Usage: $0 [path-to-micropython] [--ext_flash <size-mb>]"
  exit 1
fi

BUILD_SUFFIX=""
if [[ -n "$SPI_FLASH_SIZE_MB" ]]; then
  BUILD_SUFFIX="_FLASH_${SPI_FLASH_SIZE_MB}M"
fi

BUILD_DIR="$STM32_DIR/build-$BOARD$BUILD_SUFFIX"

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

read -p "Flash build-$BOARD$BUILD_SUFFIX firmware to device in DFU mode? (y/N): " response
if [[ ! "$response" =~ ^[Yy]$ ]]; then
  exit 0
fi

if [[ -f "$fw0" && -f "$fw1" ]]; then
  # Mass-erase wipes the WHOLE chip - firmware AND the /flash filesystem
  # (sysconfig.json, logs, dev overrides) - not just the firmware region. Only
  # offered on this path: dfu-util's mass-erase modifier hangs off a raw
  # segment download (-s ADDR:mass-erase:force), which the whole-image DfuSe
  # fallback below can't use.
  ERASE_MODIFIER=""
  read -p "Erase MCU flash before flashing? This wipes ALL flash memory, including the /flash filesystem (config/logs), not just the firmware. (y/N): " erase_response
  if [[ "$erase_response" =~ ^[Yy]$ ]]; then
    ERASE_MODIFIER=":mass-erase:force"
    echo "Will mass-erase the chip before writing."
  fi

  # Flash the raw segments so the final download can carry the DfuSe ':leave'
  # modifier - the ST ROM bootloader doesn't support DFU detach (the
  # "dfu-util: can't detach" you'd otherwise see), but ':leave' makes it jump
  # straight into the new firmware. No power cycle needed.
  dfu-util -a 0 -d 0483:df11 -s ${TEXT0_ADDR}${ERASE_MODIFIER} -D "$fw0" &&
  dfu-util -a 0 -d 0483:df11 -s $TEXT1_ADDR:leave -D "$fw1" &&
  echo "Flashed - device is rebooting into the new firmware."
else
  # Fallback: whole-image DfuSe file; the bootloader can't self-restart from
  # this path, so a manual reset/power cycle is required afterwards.
  dfu-util -a 0 -d 0483:df11 -D "$fw_dfu" -R
  echo "Flashed - power cycle or reset the board to start the new firmware."
fi
