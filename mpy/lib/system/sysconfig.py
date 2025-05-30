# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# sysconfig.py - Provide a system configuration database based on JSON

import json
import gc
import time

class SysConfig:
    """Handles loading, accessing, modifying, and saving system configuration."""

    def __init__(self, filename="sysconfig.json", DMESG=None, LOG=False):
        self.DMESG, self.LOG, self.filename = DMESG, LOG, filename
        self.config = {}

        def _log(message):
            if self.DMESG:
                self.DMESG.log(message)
            else:
                print(message)

        # Load defaults
        defaults_loaded = False
        local_defaults = None
        try:
            from defaults import DEFAULT_SYSCONFIG
            local_defaults = DEFAULT_SYSCONFIG
            defaults_loaded = True
        except (ImportError, Exception) as e:
            _log(f"SYSCONFIG: WARNING - Could not load defaults: {e}")

        # Load file config
        file_loaded = False
        file_config = None
        try:
            with open(self.filename, 'r') as f:
                file_config = json.load(f)
                file_loaded = True
        except (OSError, ValueError) as e:
            _log(f"SYSCONFIG: WARNING - '{self.filename}' not found/invalid: {e}")
        except Exception as e:
            _log(f"SYSCONFIG: WARNING - Error loading '{self.filename}': {e}")

        # Determine final configuration
        if defaults_loaded and file_loaded:
            _log(f"SYSCONFIG: Using '{self.filename}' merged with defaults")
            self.config = file_config
            self._merge_defaults(self.config, local_defaults)
            self.save()
        elif defaults_loaded:
            _log(f"SYSCONFIG: Using defaults, saving to '{self.filename}'")
            self.config = local_defaults.copy()
            self.save()
        elif file_loaded:
            _log(f"SYSCONFIG: WARNING - Using '{self.filename}' only, no defaults")
            self.config = file_config
        else:
            _log("SYSCONFIG: CRITICAL - No config or defaults available")
            while True:
                time.sleep(1)

    def load(self, default_config_source):
        """Load configuration from file."""
        try:
            with open(self.filename, 'r') as f:
                self._log(f"Loading {self.filename}")
                self.config = json.load(f)
            self._merge_defaults(self.config, default_config_source)
        except (OSError, ValueError) as e:
            self._log(f"'{self.filename}' not found/invalid ({e}), using defaults")
            self.config = default_config_source.copy()
            self.save()

    def save(self):
        """Save current configuration to file."""
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.config, f)
            self._log(f"Configuration saved to '{self.filename}'")
            gc.collect()
        except OSError as e:
            self._log(f"Error saving to '{self.filename}': {e}")

    def get(self, key, default=None):
        """Get configuration value using dot-separated key."""
        keys = key.split('.')
        value = self.config
        try:
            for k in keys:
                if isinstance(value, dict):
                    value = value[k]
                else:
                    self._log(f"Key path '{key}' invalid at '{k}'")
                    return default
            return value
        except KeyError:
            self._log(f"Key '{key}' not found")
            return default
        except TypeError:
            self._log(f"TypeError accessing '{key}'")
            return default

    def set(self, key, value, log=False):
        """Set configuration value using dot-separated key."""
        keys = key.split('.')
        conf_level = self.config
        try:
            for i, k in enumerate(keys):
                if i == len(keys) - 1:
                    conf_level[k] = value
                    if self.LOG or log:
                        self._log(f"Set '{key}' = {value}")
                else:
                    if k not in conf_level or not isinstance(conf_level[k], dict):
                        conf_level[k] = {}
                    conf_level = conf_level[k]
        except TypeError as e:
            if self.LOG or log:
                self._log(f"TypeError setting '{key}': {e}")

    def delete(self, key):
        """Delete configuration value using dot-separated key."""
        keys = key.split('.')
        conf_level = self.config
        try:
            for k in keys[:-1]:
                if isinstance(conf_level, dict):
                    conf_level = conf_level[k]
                else:
                    self._log(f"Cannot delete '{key}', invalid path at '{k}'")
                    return False

            final_key = keys[-1]
            if isinstance(conf_level, dict) and final_key in conf_level:
                del conf_level[final_key]
                self._log(f"Deleted key '{key}'")
                return True
            else:
                self._log(f"Key '{key}' not found for deletion")
                return False
        except (KeyError, TypeError) as e:
            self._log(f"Error deleting '{key}': {e}")
            return False

    def show(self):
        """Print current configuration."""
        print("  Current Configuration")
        print("=========================")
        self._print_dict_recursive(self.config)

    def _print_dict_recursive(self, d, indent=0):
        prefix = '  ' * indent
        for key, value in d.items():
            if isinstance(value, dict):
                print(f"{prefix}{key}:")
                self._print_dict_recursive(value, indent + 1)
            else:
                value_repr = f"'{value}'" if isinstance(value, str) else value
                print(f"{prefix}{key}: {value_repr}")

    def _merge_defaults(self, target, source):
        """Recursively merge source dict into target dict for missing keys."""
        for key, value in source.items():
            if isinstance(value, dict):
                node = target.get(key)
                if not isinstance(node, dict):
                    node = {}
                    target[key] = node
                self._merge_defaults(node, value)
            else:
                target.setdefault(key, value)

    def _log(self, message):
        """Internal logging helper."""
        if self.LOG:
            log_message = f"SYSCONFIG: {message}"
            if self.DMESG and hasattr(self.DMESG, 'log'):
                self.DMESG.log(log_message)
            else:
                print(log_message)