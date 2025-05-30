# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# eeprom.py - Maxim DS28E07 one-wire eeprom support

import time
from machine import Pin
import onewire

class DS28E07:
    """DS28E07 1-Wire EEPROM driver with consolidated functionality."""
    
    def __init__(self, pin_name, DMESG=None, LOG=False):
        self.DMESG, self.LOG, self.ow = DMESG, LOG, None
        
        try:
            self.ow = onewire.OneWire(Pin(pin_name))
            if self.ow.reset():
                self._log(f"OK - Pin:{pin_name}, Device detected", force=True)
            else:
                self._log(f"WARN - Pin:{pin_name}, No device found", force=True)
        except Exception as e:
            # Only log critical errors during initialization
            self._log(f"FAIL - Pin:{pin_name}, Error:{e}", force=True)

    def _log(self, msg, force=False):
        if (self.LOG or force) and self.DMESG:
            self.DMESG.log(f"EEPROM[DS28E07]: {msg}")

    def _crc8(self, data):
        """Calculate Dallas/Maxim CRC8."""
        crc = 0
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
        return crc

    def _cmd(self, cmd, addr=None, data=None):
        """Generic command helper."""
        if not self.ow or not self.ow.reset():
            return None
        self.ow.writebyte(0xCC)  # SKIP_ROM
        self.ow.writebyte(cmd)
        if addr is not None:
            self.ow.writebyte(addr & 0xFF)
            self.ow.writebyte(0x00)
        if data:
            self.ow.writebytes(data)
        return True

    def read_memory(self, addr, length):
        """Read from EEPROM memory."""
        if not (0 <= addr <= 127 and 0 < length <= 128 - addr):
            self._log(f"Invalid read params: addr={addr}, len={length}")
            return None
        
        if not self._cmd(0xF0, addr):  # READ_MEMORY
            return None
        
        try:
            data = bytes(self.ow.readbyte() for _ in range(length))
            self._log(f"Read {len(data)}B @ {addr}")
            return data
        except Exception as e:
            self._log(f"Read error: {e}")
            return None

    def write_memory(self, addr, data):
        """Write to EEPROM using scratchpad."""
        if not (0 <= addr <= 127 and 0 < len(data) <= min(8, 128 - addr)):
            self._log(f"Invalid write params: addr={addr}, len={len(data)}")
            return False
        
        try:
            # Write to scratchpad
            if not self._cmd(0x0F, addr, data):  # WRITE_SCRATCHPAD
                return False
            
            # Read and verify scratchpad
            if not self._cmd(0xAA):  # READ_SCRATCHPAD
                return False
            
            # Read header and data back
            header = [self.ow.readbyte() for _ in range(3)]  # TA1, TA2, E/S
            es_byte = header[2]
            bytes_to_read = ((es_byte & 7) - (addr & 7) + 1) % 8 or 8
            read_data = bytes(self.ow.readbyte() for _ in range(bytes_to_read))
            crc_inv = self.ow.readbyte()
            
            # Verify CRC
            expected = bytearray([0x0F, addr & 0xFF, 0x00]) + data
            if self._crc8(expected) != (~crc_inv & 0xFF):
                self._log("CRC verification failed")
                return False
            
            # Copy scratchpad to memory
            if not self._cmd(0x55, addr):  # COPY_SCRATCHPAD
                return False
            self.ow.writebyte(es_byte)
            time.sleep_ms(10)  # Copy delay
            
            # Check completion
            if self.ow.readbit() != 1:
                self._log("Copy completion warning")
            
            self._log(f"Wrote {len(data)}B @ {addr}")
            return True
            
        except Exception as e:
            self._log(f"Write error: {e}")
            return False

