# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# eeprom.py - EEPROM factory for dynamic driver loading

class EEPROM:
    """EEPROM factory class that loads appropriate drivers based on type."""
    
    def __init__(self, pin_name, driver='DS28E07', DMESG=None, LOG=False):
        """Initialize EEPROM with specified driver.
        
        Args:
            pin_name: Pin name for EEPROM connection
            driver: Driver name ('DS28E07', 'AT21CS01', etc.)
            DMESG: Optional logging instance  
            LOG: Enable debug logging
        """
        self.DMESG = DMESG
        self.LOG = LOG
        self.driver_name = driver.upper()
        
        # Load the appropriate driver
        if self.driver_name == 'DS28E07':
            self._load_ds28e07_driver(pin_name)
        elif self.driver_name == 'AT21CS01':
            self._load_at21cs01_driver(pin_name)
        else:
            raise ValueError(f"Unsupported EEPROM driver: {driver}")
    
    def _load_ds28e07_driver(self, pin_name):
        """Load the DS28E07 driver from eeprom_ds28e07.py."""
        try:
            # Import the DS28E07 implementation
            from hardware.eeprom_ds28e07 import DS28E07
            self._driver = DS28E07(pin_name, DMESG=self.DMESG, LOG=self.LOG)
            
        except ImportError as e:
            raise ImportError(f"Could not load DS28E07 driver: {e}")
    
    def _load_at21cs01_driver(self, pin_name):
        """Load the AT21CS01 driver from eeprom_at21cs01.py."""
        try:
            # Import the AT21CS01 implementation
            from hardware.eeprom_at21cs01 import AT21CS01
            self._driver = AT21CS01(pin_name, DMESG=self.DMESG, LOG=self.LOG)

        except ImportError as e:
            raise ImportError(f"Could not load AT21CS01 driver: {e}")
    
    # Delegate all EEPROM operations to the underlying driver
    def read_memory(self, addr, length):
        """Read from EEPROM memory."""
        return self._driver.read_memory(addr, length)
    
    def write_memory(self, addr, data):
        """Write to EEPROM memory."""
        return self._driver.write_memory(addr, data)
    
    # Optional methods (driver-dependent)
    def read_serial_number(self):
        """Read device serial number (if supported)."""
        if hasattr(self._driver, 'read_serial_number'):
            return self._driver.read_serial_number()
        return None
    
    def get_device_info(self):
        """Get device information (if supported)."""
        if hasattr(self._driver, 'get_device_info'):
            return self._driver.get_device_info()
        return None
    
    # Delegate any other method calls to the driver
    def __getattr__(self, name):
        """Delegate unknown method calls to the driver."""
        return getattr(self._driver, name)
    
    @property
    def driver(self):
        """Get the underlying driver instance."""
        return self._driver