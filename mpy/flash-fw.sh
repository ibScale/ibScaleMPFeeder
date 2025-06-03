#!/bin/bash

project = $(basename "$(pwd)")
default = ../../build-$project/firmware.dfu

# Ask the user if they want to clean the build
read -p "Flash firmware to device? (y/N): " response

# Flash firmware
if [[ "$response" =~ ^[Yy]$ ]]; then
  dfu-util -a 0 -D ../../build-$project/firmware.dfu -R
fi