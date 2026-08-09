#!/bin/bash
# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>
#
# compile-fw.sh - Build the Gluon firmware.
#
# Run from the mpy/ directory:
#   ./compile-fw.sh [path-to-micropython-source] [--ext_flash <size-mb>]
#
# If the MicroPython path is not provided it defaults to ../../micropython,
# which assumes this repo and the MicroPython source are siblings:
#   parent/
#   ├── micropython/
#   └── ibScaleMPFeeder/
#       └── mpy/   <-- run from here
#
# Assumes no external SPI flash chip is present (the standard build; internal 48K
# filesystem). To build for a board with one populated, opt in explicitly with
# --ext_flash <size-mb> (e.g. --ext_flash 4). See docs/INSTALL.md.

set -e

BOARD=ibScaleMPFeeder
BOARD_DIR="$(cd "$(dirname "$0")" && pwd)"   # absolute path to mpy/

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

if [[ ! -d "$MPY_DIR/ports/stm32" ]]; then
  echo "MicroPython source not found at '$MPY_DIR'."
  echo "Usage: $0 [path-to-micropython] [--ext_flash <size-mb>]"
  echo "Example: $0 ~/src/micropython --ext_flash 4"
  exit 1
fi

MPY_DIR="$(cd "$MPY_DIR" && pwd)"   # resolve to absolute path
STM32_DIR="$MPY_DIR/ports/stm32"

# External SPI flash build: swaps /flash from internal (48K) to an external SPI NOR
# chip, mainly so dev work (file-shadowing a frozen module on /flash) isn't cramped
# by the internal filesystem's size. Off unless --ext_flash was given.
MAKE_EXTRA_ARGS=()
BUILD_SUFFIX=""
if [[ -n "$SPI_FLASH_SIZE_MB" ]]; then
  MAKE_EXTRA_ARGS+=("SPI_FLASH_SIZE_MB=$SPI_FLASH_SIZE_MB")
  BUILD_SUFFIX="_FLASH_${SPI_FLASH_SIZE_MB}M"
  echo "Building for external SPI flash (${SPI_FLASH_SIZE_MB}MB)."
fi

read -p "Clean build directory first? (y/N): " response
if [[ "$response" =~ ^[Yy]$ ]]; then
  echo "Cleaning..."
  make -C "$STM32_DIR" BOARD=$BOARD BOARD_DIR="$BOARD_DIR" "${MAKE_EXTRA_ARGS[@]}" clean
fi

echo "Building mpy-cross (required for frozen modules)..."
make -C "$MPY_DIR/mpy-cross"

echo "Updating submodules..."
make -C "$STM32_DIR" BOARD=$BOARD BOARD_DIR="$BOARD_DIR" submodules

echo "Building firmware..."
make -C "$STM32_DIR" BOARD=$BOARD BOARD_DIR="$BOARD_DIR" "${MAKE_EXTRA_ARGS[@]}"

echo ""
echo "Done: $STM32_DIR/build-$BOARD$BUILD_SUFFIX/firmware.dfu"
