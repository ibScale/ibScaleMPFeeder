# SPDX-License-Identifier: GPL-3.0 
# Copyright (C) 2025 FexTel, Inc. <info@ibscale.com>
# Author: James Pearson <jamesp@ibscale.com>

# sysconfig.py - Provide a system configuration database based on JSON

import json
import gc
import os

class SysConfig:
    """Handles loading, accessing, modifying, and saving system configuration."""

    def __init__(self, filename="sysconfig.json", DMESG=None, LOG=False):
        self.DMESG, self.LOG, self.filename = DMESG, LOG, filename
        self.config = {}
        # Cached once; used both for the interrupted-save recovery check below and
        # by save() on every write, avoiding a repeated string concat per save.
        self._tmp_filename = filename + '.tmp'

        # Load defaults
        defaults_loaded = False
        local_defaults = None
        try:
            from defaults import DEFAULT_SYSCONFIG
            local_defaults = DEFAULT_SYSCONFIG
            defaults_loaded = True
        except Exception as e:
            self._log(f"WARNING - Could not load defaults: {e}", force=True)

        # Load file config. If the primary file is missing/corrupt, fall back to the
        # temp file left by an interrupted save() so a brown-out mid-write self-heals.
        file_loaded = False
        file_config = None
        for path in (self.filename, self._tmp_filename):
            try:
                with open(path, 'r') as f:
                    file_config = json.load(f)
                file_loaded = True
                if path != self.filename:
                    self._log(f"Recovered config from '{path}' after interrupted save", force=True)
                break
            except (OSError, ValueError) as e:
                self._log(f"WARNING - '{path}' not found/invalid: {e}", force=True)
            except Exception as e:
                self._log(f"WARNING - Error loading '{path}': {e}", force=True)

        # Determine final configuration
        if defaults_loaded and file_loaded:
            self.config = file_config
            if self._merge_defaults(self.config, local_defaults):
                self._log(f"Updated '{self.filename}' with missing defaults", force=True)
                self.save()
            else:
                self._log(f"Using '{self.filename}' (already complete)", force=True)
        elif defaults_loaded:
            self._log(f"Using defaults, saving to '{self.filename}'", force=True)
            # Deep-copy via the merge so we never mutate the module-level DEFAULT_SYSCONFIG
            # (a plain dict.copy() would share the nested per-subsystem dicts).
            self.config = {}
            self._merge_defaults(self.config, local_defaults)
            self.save()
        elif file_loaded:
            self._log(f"WARNING - Using '{self.filename}' only, no defaults", force=True)
            self.config = file_config
        else:
            self._log("CRITICAL - No config or defaults available", force=True)
            raise RuntimeError("SysConfig: no configuration file or defaults available")

    def save(self):
        """Save configuration atomically: write a temp file, then rename over the original.

        An interrupted write (e.g. brown-out) can only damage the temp file, never the live
        config, and __init__ recovers from the temp file if the primary is missing/corrupt.
        """
        tmp = self._tmp_filename
        try:
            with open(tmp, 'w') as f:
                f.write(json.dumps(self.config))  # single write; smaller corruption window
            # FAT rename won't overwrite an existing file, so remove the old one first.
            # (littlefs would rename atomically without this; the extra remove is harmless.)
            try:
                os.remove(self.filename)
            except OSError:
                pass
            os.rename(tmp, self.filename)
            self._log(f"Configuration saved to '{self.filename}'")
            gc.collect()
        except OSError as e:
            self._log(f"Error saving to '{self.filename}': {e}")
            try:
                os.remove(tmp)
            except OSError:
                pass

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
        """Recursively merge source into target for missing keys. Returns True if target changed."""
        changed = False
        for key, value in source.items():
            if isinstance(value, dict):
                node = target.get(key)
                if not isinstance(node, dict):
                    node = {}
                    target[key] = node
                    changed = True
                if self._merge_defaults(node, value):
                    changed = True
            else:
                if key not in target:
                    target[key] = value
                    changed = True
        return changed

    def _log(self, message, force=False):
        """Internal logging helper. force=True always logs (init/warning/error messages);
        otherwise gated by self.LOG, matching the _log(msg, force=False) pattern used
        elsewhere in the codebase (servo.py, bootstrap.py, buttons.py, peel.py).
        """
        if not (self.LOG or force):
            return
        log_message = f"SYSCONFIG: {message}"
        if self.DMESG and hasattr(self.DMESG, 'log'):
            self.DMESG.log(log_message)
        else:
            print(log_message)