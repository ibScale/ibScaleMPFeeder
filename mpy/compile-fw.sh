#!/bin/bash
# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# compile-fw.sh - Compile the firmware under linux using micropython

# Get board name
board=$(basename "$(pwd)")
cd ../..

# Ask the user if they want to clean the build
read -p "Clean the build directory first? (y/N): " response

# Check the response (case-insensitive)
if [[ "$response" =~ ^[Yy]$ ]]; then
  echo "Cleaning build directory..."
  make BOARD=$board clean
else
  echo "Skipping clean step."
fi

# Continue with the rest of the build process
echo "Updating submodules..."
make BOARD=$board submodules

echo "Building firmware..."
make BOARD=$board