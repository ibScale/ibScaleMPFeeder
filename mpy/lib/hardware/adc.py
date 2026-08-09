# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# adc.py - ADC lookup for VDC, System, and Temperature

import pyb
import machine

class ADCReader:
    def __init__(self, DMESG=None, VDDA=3.3, VMONVDC_PIN="VMONVDC", VMONSYS_PIN="VMON10V",
                 ADC_BITS=12, VMONSYS_RATIO=4.0303, VMONVDC_RATIO=7.6667, LOG=False):
        self.VDDA = VDDA
        self.LOG, self.DMESG = LOG, DMESG
        self._vdc_ratio = VMONVDC_RATIO
        self._sys_ratio = VMONSYS_RATIO
        self.adcs = []

        try:
            self.adcs = [
                machine.ADC(VMONVDC_PIN),
                machine.ADC(VMONSYS_PIN),
                # Mask 0x70000 = internal channels only (16 temp, 17 vref, 18 vbat).
                # The default mask (0xffffffff) would reconfigure EVERY ADC-capable
                # pin (PA0-7, PB0-1, PC0-5) to analog - clobbering RS485 DE/TX/RX
                # and the SPI-flash pins in that build variant.
                pyb.ADCAll(ADC_BITS, 0x70000),
            ]
            self._log(f"Init - Bits:{ADC_BITS}, VDDA:{VDDA}, VDC:{VMONVDC_PIN}({VMONVDC_RATIO}x)={self.vmonvdc():.2f}V, VSYS:{VMONSYS_PIN}({VMONSYS_RATIO}x)={self.vmonsys():.2f}V", force=True)
        except Exception as e:
            self.adcs = []
            self._log(f"FAIL: {e}", force=True)

    def _log(self, m, force=False):
        if (self.LOG or force) and self.DMESG:
            self.DMESG.log(f"ADC: {m}")

    def _read(self, idx, ratio):
        if idx >= len(self.adcs):
            return None
        try:
            return self.adcs[idx].read_u16() * self.VDDA / 65535 * ratio
        except Exception:
            return None

    def vmonvdc(self): return self._read(0, self._vdc_ratio)
    def vmonsys(self): return self._read(1, self._sys_ratio)
    def temp(self): return self.adcs[2].read_core_temp() if len(self.adcs) > 2 else None
