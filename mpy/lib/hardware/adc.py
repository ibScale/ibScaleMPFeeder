# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# adc.py - ADC lookup for VDC, System, and Temperature

import pyb

class ADCReader:
    def __init__(self, DMESG=None, VDDA=3.3, VMONVDC_PIN="VMONVDC", VMONSYS_PIN="VMON10V", 
                 ADC_BITS=12, VMONSYS_RATIO=4.0303, VMONVDC_RATIO=7.6667, LOG=False):
        
        # Input validation
        if not (1.0 <= VDDA <= 5.0):
            raise ValueError(f"VDDA must be between 1.0V and 5.0V, got {VDDA}V")
        if not (8 <= ADC_BITS <= 16):
            raise ValueError(f"ADC bits must be between 8 and 16, got {ADC_BITS}")
        if not (0.1 <= VMONSYS_RATIO <= 100.0):
            raise ValueError(f"System voltage ratio must be between 0.1 and 100.0, got {VMONSYS_RATIO}")
        if not (0.1 <= VMONVDC_RATIO <= 100.0):
            raise ValueError(f"VDC voltage ratio must be between 0.1 and 100.0, got {VMONVDC_RATIO}")
        if not isinstance(VMONVDC_PIN, str) or not VMONVDC_PIN:
            raise ValueError("VDC pin name must be a non-empty string")
        if not isinstance(VMONSYS_PIN, str) or not VMONSYS_PIN:
            raise ValueError("System pin name must be a non-empty string")
        
        self.VDDA, self.max_val, self.LOG, self.DMESG = VDDA, (1<<ADC_BITS)-1, LOG, DMESG
        self.ratios, self.err = [VMONVDC_RATIO, VMONSYS_RATIO], None
        
        try:
            self.adcs = [pyb.ADC(pyb.Pin(VMONVDC_PIN)), pyb.ADC(pyb.Pin(VMONSYS_PIN)), pyb.ADCAll(ADC_BITS, int(VDDA*1000))]
            
            # Read initial values for the log
            vdc_reading = self.vmonvdc()
            vsys_reading = self.vmonsys()
            
            self._log(f"Init - Bits: {ADC_BITS}, VDDA: {VDDA}, VDC: {VMONVDC_PIN}({VMONVDC_RATIO}x)={vdc_reading:.2f}V, VSYS: {VMONSYS_PIN}({VMONSYS_RATIO}x)={vsys_reading:.2f}V", force=True)
        except Exception as e:
            self.err, self.adcs = str(e), []
            self._log(f"FAIL: {e}", force=True)

    def _log(self, m, force=False):
        if (self.LOG or force) and self.DMESG: 
            self.DMESG.log(f"ADC: {m}")

    def _read(self, idx, ratio_idx=None):
        if idx >= len(self.adcs): return None
        try:
            v = self.adcs[idx].read() * self.VDDA / self.max_val
            return v * self.ratios[ratio_idx] if ratio_idx is not None else v
        except: return None

    def vmonvdc(self): return self._read(0, 0)
    def vmonsys(self): return self._read(1, 1)
    def vref(self): return self.adcs[2].read_core_vref() if len(self.adcs) > 2 else None
    def temp(self): return self.adcs[2].read_core_temp() if len(self.adcs) > 2 else None
