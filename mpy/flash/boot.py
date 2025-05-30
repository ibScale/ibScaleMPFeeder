# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# boot.py -- run on boot to configure USB and filesystem

import pyb
pyb.main('main.py') # main script to run after this one
pyb.usb_mode('VCP+MSC') # act as a serial and a storage device
