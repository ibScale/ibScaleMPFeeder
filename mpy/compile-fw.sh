#!/bin/bash
# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>
#
# compile-fw.sh - Build the Gluon firmware.
#
# Run from the mpy/ directory:
#   ./compile-fw.sh [path-to-micropython-source]
#
# If the MicroPython path is not provided it defaults to ../../micropython,
# which assumes this repo and the MicroPython source are siblings:
#   parent/
#   ├── micropython/
#   └── ibScaleMPFeeder/
#       └── mpy/   <-- run from here

set -e

BOARD=ibScaleMPFeeder
BOARD_DIR="$(cd "$(dirname "$0")" && pwd)"   # absolute path to mpy/
MPY_DIR="${1:-../../micropython}"

if [[ ! -d "$MPY_DIR/ports/stm32" ]]; then
  echo "MicroPython source not found at '$MPY_DIR'."
  echo "Usage: $0 [path-to-micropython]"
  echo "Example: $0 ~/src/micropython"
  exit 1
fi

MPY_DIR="$(cd "$MPY_DIR" && pwd)"   # resolve to absolute path
STM32_DIR="$MPY_DIR/ports/stm32"

read -p "Clean build directory first? (y/N): " response
if [[ "$response" =~ ^[Yy]$ ]]; then
  echo "Cleaning..."
  make -C "$STM32_DIR" BOARD=$BOARD BOARD_DIR="$BOARD_DIR" clean
fi

echo "Building mpy-cross (required for frozen modules)..."
make -C "$MPY_DIR/mpy-cross"

echo "Updating submodules..."
make -C "$STM32_DIR" BOARD=$BOARD BOARD_DIR="$BOARD_DIR" submodules

echo "Building firmware..."
make -C "$STM32_DIR" BOARD=$BOARD BOARD_DIR="$BOARD_DIR"

echo ""
echo "Done: $STM32_DIR/build-$BOARD/firmware.dfu"
