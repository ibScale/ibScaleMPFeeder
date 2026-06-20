# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>
#
# boot.py - Runs before main.py. Sets USB to VCP-only for normal operation.
# MSC is compiled in (MICROPY_HW_USB_MSC=1) so it can be re-enabled at runtime
# via pyb.usb_mode('VCP+MSC') when dropping to the REPL for filesystem access.

import pyb

pyb.usb_mode("VCP")
