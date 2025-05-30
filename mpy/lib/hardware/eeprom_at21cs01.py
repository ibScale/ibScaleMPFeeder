# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# eeprom_at21cs01.py - Microchip one-wire driver for the AT21CS01-STUM10-T
# THIS IS BETA! Needs rigorous testing! But should be *close* to working

import time
from machine import Pin
import onewire

class AT21CS01:
    """Microchip AT21CS01-STUM10 1-Wire EEPROM driver (128 bytes + SN area)."""
    
    def _log(self, msg, force=False):
        if (self.LOG or force) and self.DMESG:
            self.DMESG.log(f"EEPROM[AT21CS01]: {msg}")

    def __init__(self, pin_name, DMESG=None, LOG=False):
        """Initialize AT21CS01-STUM10 1-Wire EEPROM.
        
        Args:
            pin_name: Pin name for 1-Wire connection
            DMESG: Optional logging instance
            LOG: Enable debug logging
        """
        self.DMESG, self.LOG, self.ow = DMESG, LOG, None
        
        try:
            self.ow = onewire.OneWire(Pin(pin_name))
            if self.ow.reset():
                # Check if it's an AT21CS01 by reading ROM
                rom = self._read_rom()
                if rom and rom[0] == 0x43:  # AT21CS01 family code
                    self._log(f"OK - Pin:{pin_name}, AT21CS01 detected, ROM:{rom.hex()}", force=True)
                elif rom:
                    self._log(f"WARN - Pin:{pin_name}, Unknown device, ROM:{rom.hex()}", force=True)
                else:
                    self._log(f"OK - Pin:{pin_name}, Device detected", force=True)
            else:
                self._log(f"WARN - Pin:{pin_name}, No device found", force=True)
        except Exception as e:
            self._log(f"FAIL - Pin:{pin_name}, Error:{e}", force=True)

    def _read_rom(self):
        """Read device ROM (8 bytes) for identification."""
        try:
            if not self.ow or not self.ow.reset():
                return None
            self.ow.writebyte(0x33)  # READ_ROM
            rom = bytes(self.ow.readbyte() for _ in range(8))
            return rom
        except:
            return None

    def _crc8(self, data):
        """Calculate Dallas/Maxim CRC8."""
        crc = 0
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
        return crc

    def read_memory(self, addr, length):
        """Read from AT21CS01 EEPROM memory (0x00-0x7F user area)."""
        if not (0 <= addr <= 127 and 0 < length <= 128 - addr):
            self._log(f"Invalid read params: addr={addr}, len={length}")
            return None
        
        if not self.ow or not self.ow.reset():
            return None
        
        try:
            # AT21CS01 Read Memory command sequence
            self.ow.writebyte(0xCC)  # SKIP_ROM
            self.ow.writebyte(0xF0)  # READ_MEMORY
            self.ow.writebyte(addr & 0xFF)
            self.ow.writebyte(0x00)  # High address byte (always 0 for user area)
            
            data = bytes(self.ow.readbyte() for _ in range(length))
            self._log(f"Read {len(data)}B @ {addr}")
            return data
            
        except Exception as e:
            self._log(f"Read error: {e}")
            return None

    def write_memory(self, addr, data):
        """Write to AT21CS01 EEPROM using scratchpad (max 8 bytes per write)."""
        if not isinstance(data, (bytes, bytearray)):
            data = bytes(data)
        
        if not (0 <= addr <= 127 and 0 < len(data) <= min(8, 128 - addr)):
            self._log(f"Invalid write params: addr={addr}, len={len(data)}")
            return False
        
        # Check 8-byte boundary alignment for optimal writes
        boundary_end = ((addr >> 3) + 1) << 3  # Next 8-byte boundary
        if addr + len(data) > boundary_end:
            self._log(f"Write crosses 8-byte boundary: addr={addr}, len={len(data)}")
            # AT21CS01 can handle this, but warn about potential performance
        
        if not self.ow or not self.ow.reset():
            return False
        
        try:
            # Step 1: Write to scratchpad
            self.ow.writebyte(0xCC)  # SKIP_ROM
            self.ow.writebyte(0x0F)  # WRITE_SCRATCHPAD
            self.ow.writebyte(addr & 0xFF)
            self.ow.writebyte(0x00)  # High address byte
            
            for byte in data:
                self.ow.writebyte(byte)
            
            # Step 2: Read scratchpad for verification
            if not self.ow.reset():
                return False
            
            self.ow.writebyte(0xCC)  # SKIP_ROM
            self.ow.writebyte(0xAA)  # READ_SCRATCHPAD
            
            # Read target address, E/S byte, and data
            ta1 = self.ow.readbyte()
            ta2 = self.ow.readbyte()
            es_byte = self.ow.readbyte()
            
            # Calculate expected data length in scratchpad
            ending_addr = (addr + len(data) - 1) & 0x07
            scratchpad_len = ending_addr + 1
            
            verify_data = bytes(self.ow.readbyte() for _ in range(scratchpad_len))
            crc = self.ow.readbyte()
            
            # Verify scratchpad contents
            if verify_data[:len(data)] != data:
                self._log("Scratchpad verification failed")
                return False
            
            # Step 3: Copy scratchpad to EEPROM
            if not self.ow.reset():
                return False
            
            self.ow.writebyte(0xCC)  # SKIP_ROM
            self.ow.writebyte(0x55)  # COPY_SCRATCHPAD
            self.ow.writebyte(ta1)
            self.ow.writebyte(ta2)
            self.ow.writebyte(es_byte)
            
            # Wait for copy completion (max 10ms for AT21CS01)
            time.sleep_ms(12)
            
            # Check completion status
            if self.ow.readbit() != 1:
                self._log("Copy completion warning")
            
            self._log(f"Wrote {len(data)}B @ {addr}")
            return True
            
        except Exception as e:
            self._log(f"Write error: {e}")
            return False

    def read_serial_number(self):
        """Read 8-byte factory ROM including serial number."""
        rom = self._read_rom()
        if rom and len(rom) == 8:
            # ROM format: [Family Code][6-byte SN][CRC]
            serial_number = rom[1:7]  # Extract 6-byte serial number
            self._log(f"Read serial number: {serial_number.hex()}")
            return serial_number
        else:
            self._log("Failed to read serial number")
            return None

    def get_device_info(self):
        """Get complete device information."""
        rom = self._read_rom()
        if rom and len(rom) == 8:
            return {
                'family_code': rom[0],
                'serial_number': rom[1:7],
                'crc': rom[7],
                'full_rom': rom
            }
        return None