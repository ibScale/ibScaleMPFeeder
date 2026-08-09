# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# manifest.py - Micropython libraries and frozen files aka the Slushy Machine!

# Comment out a line and then recompile the firmware to unfreeze. Once unfrozen, you'll
# need to copy the file to the onboard flash so it's usable by the application code and
# editable by you. You can also just edit the file where it's at and recompile the 
# firmware to test aka doing it C style. Be warned, some of these files are so big that
# working with them frozen is the only way to go without adding an external SPI flash 
# chip and enabling firmware support for it.
#
# Alternatively, a file on the flash takes precedence over a frozen file, but you will
# still have the same space limitations since there's only 48Kb of usable flash space.
# A frozen file is also significantly faster since it executes as pre-compiled byte code
# although still significantly slower versus native or viper code.

# Micropython base setup
include("$(PORT_DIR)/boards/manifest.py")
require("time")
require("os-path")
require("aiorepl")

# Appliance entry scripts - frozen so the flashed image is self-contained and boots
# with nothing on the filesystem.
# boot.py sets USB to VCP-only; MSC is re-enabled at runtime when dropping to the REPL.
# main.py runs frozen-first (a /flash copy is ignored).
# a /flash/app.py copy still shadows the frozen app.py for dev overrides.
freeze("$(BOARD_DIR)/flash", script="boot.py")
freeze("$(BOARD_DIR)/flash", script="main.py")
freeze("$(BOARD_DIR)/flash", script="app.py")

# Application stuff
freeze("$(BOARD_DIR)/lib", script="application/packetizer.py")
freeze("$(BOARD_DIR)/lib", script="application/photon.py")

# Everything else
freeze("$(BOARD_DIR)/lib", script="defaults.py")
freeze("$(BOARD_DIR)/lib", script="system/dmesg.py")
freeze("$(BOARD_DIR)/lib", script="system/sysconfig.py")
freeze("$(BOARD_DIR)/lib", script="system/bootstrap.py")
freeze("$(BOARD_DIR)/lib", script="system/servo.py")
freeze("$(BOARD_DIR)/lib", script="system/console.py")
freeze("$(BOARD_DIR)/lib", script="system/watchdog.py")
freeze("$(BOARD_DIR)/lib", script="system/gcutil.py")
freeze("$(BOARD_DIR)/lib", script="system/peel.py")
freeze("$(BOARD_DIR)/lib", script="util/misc.py")
freeze("$(BOARD_DIR)/lib", script="util/calibrate.py")
freeze("$(BOARD_DIR)/lib", script="util/profiler.py")
freeze("$(BOARD_DIR)/lib", script="hardware/buttons.py")
freeze("$(BOARD_DIR)/lib", script="hardware/adc.py")
freeze("$(BOARD_DIR)/lib", script="hardware/led.py")
freeze("$(BOARD_DIR)/lib", script="hardware/drives.py")
freeze("$(BOARD_DIR)/lib", script="hardware/encoder.py")
freeze("$(BOARD_DIR)/lib", script="hardware/rs485.py")
freeze("$(BOARD_DIR)/lib", script="hardware/eeprom.py")
freeze("$(BOARD_DIR)/lib", script="hardware/eeprom_ds28e07.py")
freeze("$(BOARD_DIR)/lib", script="hardware/eeprom_at21cs01.py")
